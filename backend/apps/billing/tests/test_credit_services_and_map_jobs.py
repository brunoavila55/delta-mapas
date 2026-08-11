from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.db import connection
from django.test import override_settings
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import Membership
from apps.billing.exceptions import CreditOperationConflict, InsufficientCredits
from apps.billing.models import CreditAccount, CreditTransaction, ProcessingPrice
from apps.billing.services import (
    adjust_available_credits,
    capture_reserved_credits,
    release_reserved_credits,
    reserve_credits,
)
from apps.maps.exceptions import (
    CopernicusConfigurationError,
    MapRenderingError,
    NoSatelliteSceneFound,
    SatelliteCatalogError,
    SatelliteProcessUnavailable,
)
from apps.maps.models import MapJob
from apps.maps.services.copernicus import CopernicusScene
from apps.maps.services.pipeline import PipelineProcessingResult
from apps.maps.tasks import process_map_job
from apps.properties.models import Property


@override_settings(SECRET_KEY="test-secret-key-with-at-least-thirty-two-bytes")
class BillingAndMapJobTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Tenant de billing"
        return tenant

    @staticmethod
    def get_test_schema_name():
        return "test_billing_maps"

    @staticmethod
    def get_test_tenant_domain():
        return "billing.test.localhost"

    def setUp(self):
        super().setUp()
        connection.set_tenant(self.tenant)
        User = get_user_model()
        self.user = User.objects.create_user(
            username="billing-user",
            email="billing@example.com",
            password="test-password-123",
        )
        Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            role=Membership.Role.OWNER,
        )
        self.client = APIClient(HTTP_HOST=self.get_test_tenant_domain())
        self.client.force_authenticate(self.user)
        self.account = CreditAccount.objects.create(
            singleton_key=True,
            available_balance=5,
        )
        self.price = ProcessingPrice.objects.create(
            index_type="NDVI",
            credit_cost=1,
        )
        polygon = Polygon(
            (
                (-48.01, -15.01),
                (-48.01, -15.00),
                (-48.00, -15.00),
                (-48.00, -15.01),
                (-48.01, -15.01),
            ),
            srid=4326,
        )
        self.geometry = MultiPolygon(polygon, srid=4326)
        self.property = Property.objects.create(
            name="Fazenda para job",
            geometry=self.geometry,
            created_by=self.user,
        )

    def create_job(self) -> MapJob:
        return MapJob.objects.create(
            geometry_snapshot=self.geometry,
            property=self.property,
            date_from="2026-07-01",
            date_to="2026-07-31",
            created_by=self.user,
        )

    def job_payload(self, **overrides):
        payload = {
            "index_type": "NDVI",
            "property_id": str(self.property.id),
            "date_from": "2026-07-01",
            "date_to": "2026-07-31",
            "max_cloud_cover": 20,
        }
        payload.update(overrides)
        return payload

    @patch("apps.maps.tasks.CopernicusSceneService.search_best_scene")
    def test_cancel_job_releases_credit_once_and_stops_worker(self, search):
        job = self.create_job()
        reserve_credits(
            map_job=job,
            amount=1,
            idempotency_key=f"map-job:{job.id}:reserve",
            created_by=self.user,
        )

        first = self.client.post(f"/api/v1/map-jobs/{job.id}/cancel/")
        replay = self.client.post(f"/api/v1/map-jobs/{job.id}/cancel/")
        task_result = process_map_job.apply(
            args=(str(job.id), self.tenant.schema_name)
        ).get()

        job.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay["Idempotent-Replayed"], "true")
        self.assertEqual(job.status, MapJob.Status.CANCELLED)
        self.assertEqual(job.cancelled_by, self.user)
        self.assertIsNotNone(job.cancelled_at)
        self.assertEqual(task_result, MapJob.Status.CANCELLED)
        self.assertEqual(self.account.available_balance, 5)
        self.assertEqual(self.account.reserved_balance, 0)
        self.assertEqual(CreditTransaction.objects.count(), 2)
        search.assert_not_called()

    @patch("apps.maps.tasks.process_map_job.delay")
    def test_reprocess_terminal_job_is_idempotent_and_reserves_credit(self, delay):
        delay.return_value = SimpleNamespace(id="reprocessed-task")
        source = self.create_job()
        source.status = MapJob.Status.FAILED
        source.current_step = "Falha anterior"
        source.save(update_fields=("status", "current_step"))

        first = self.client.post(
            f"/api/v1/map-jobs/{source.id}/reprocess/",
            HTTP_IDEMPOTENCY_KEY="reprocess-source-once",
        )
        replay = self.client.post(
            f"/api/v1/map-jobs/{source.id}/reprocess/",
            HTTP_IDEMPOTENCY_KEY="reprocess-source-once",
        )

        self.account.refresh_from_db()
        reprocessed = MapJob.objects.exclude(pk=source.pk).get()
        self.assertEqual(first.status_code, 202, first.data)
        self.assertEqual(replay.status_code, 202, replay.data)
        self.assertEqual(replay["Idempotent-Replayed"], "true")
        self.assertEqual(first.data["id"], replay.data["id"])
        self.assertEqual(reprocessed.reprocessed_from, source)
        self.assertEqual(reprocessed.status, MapJob.Status.PENDING)
        self.assertEqual(reprocessed.celery_task_id, "reprocessed-task")
        self.assertEqual(self.account.available_balance, 4)
        self.assertEqual(self.account.reserved_balance, 1)
        self.assertEqual(CreditTransaction.objects.count(), 1)
        delay.assert_called_once()

    def test_active_job_cannot_be_reprocessed_and_failed_job_cannot_be_cancelled(self):
        active = self.create_job()
        failed = self.create_job()
        failed.status = MapJob.Status.FAILED
        failed.save(update_fields=("status",))

        reprocess = self.client.post(
            f"/api/v1/map-jobs/{active.id}/reprocess/",
            HTTP_IDEMPOTENCY_KEY="active-reprocess",
        )
        cancel = self.client.post(f"/api/v1/map-jobs/{failed.id}/cancel/")

        self.assertEqual(reprocess.status_code, 409)
        self.assertEqual(reprocess.data["code"], "job_not_reprocessable")
        self.assertEqual(cancel.status_code, 409)
        self.assertEqual(cancel.data["code"], "job_not_cancellable")

    def test_reserve_and_capture_are_idempotent(self):
        job = self.create_job()
        first_reserve = reserve_credits(
            map_job=job,
            amount=1,
            idempotency_key=f"map-job:{job.id}:reserve",
            created_by=self.user,
        )
        replayed_reserve = reserve_credits(
            map_job=job,
            amount=1,
            idempotency_key=f"map-job:{job.id}:reserve",
            created_by=self.user,
        )
        first_capture = capture_reserved_credits(map_job=job, created_by=self.user)
        replayed_capture = capture_reserved_credits(map_job=job, created_by=self.user)

        self.account.refresh_from_db()
        self.assertFalse(first_reserve.replayed)
        self.assertTrue(replayed_reserve.replayed)
        self.assertFalse(first_capture.replayed)
        self.assertTrue(replayed_capture.replayed)
        self.assertEqual(self.account.available_balance, 4)
        self.assertEqual(self.account.reserved_balance, 0)
        self.assertEqual(CreditTransaction.objects.count(), 2)

    def test_release_restores_balance_and_blocks_capture(self):
        job = self.create_job()
        reserve_credits(
            map_job=job,
            amount=1,
            idempotency_key=f"map-job:{job.id}:reserve",
            created_by=self.user,
        )
        first = release_reserved_credits(map_job=job, created_by=self.user)
        replay = release_reserved_credits(map_job=job, created_by=self.user)

        self.account.refresh_from_db()
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(self.account.available_balance, 5)
        self.assertEqual(self.account.reserved_balance, 0)
        with self.assertRaises(CreditOperationConflict):
            capture_reserved_credits(map_job=job, created_by=self.user)

    def test_insufficient_balance_rolls_back_reservation(self):
        job = self.create_job()
        self.account.available_balance = 0
        self.account.save(update_fields=("available_balance", "updated_at"))

        with self.assertRaises(InsufficientCredits):
            reserve_credits(
                map_job=job,
                amount=1,
                idempotency_key=f"map-job:{job.id}:reserve",
                created_by=self.user,
            )

        self.account.refresh_from_db()
        self.assertEqual(self.account.reserved_balance, 0)
        self.assertEqual(CreditTransaction.objects.count(), 0)

    def test_admin_adjustment_is_audited_and_idempotent(self):
        first = adjust_available_credits(
            delta=3,
            idempotency_key="admin-adjustment-1",
            reason="Crédito de homologação",
            created_by=self.user,
        )
        replay = adjust_available_credits(
            delta=3,
            idempotency_key="admin-adjustment-1",
            reason="Crédito de homologação",
            created_by=self.user,
        )

        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.account.available_balance, 8)
        self.assertEqual(CreditTransaction.objects.count(), 1)
        entry = CreditTransaction.objects.get()
        entry.amount = 99
        with self.assertRaises(ValueError):
            entry.save()
        with self.assertRaises(ValueError):
            entry.delete()

    @patch("apps.maps.tasks.process_map_job.delay")
    def test_map_job_api_reserves_once_and_replays_same_request(self, delay):
        delay.return_value = SimpleNamespace(id="celery-task-123")

        first = self.client.post(
            "/api/v1/map-jobs/",
            self.job_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY="request-map-1",
        )
        replay = self.client.post(
            "/api/v1/map-jobs/",
            self.job_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY="request-map-1",
        )

        self.assertEqual(first.status_code, 202, first.data)
        self.assertEqual(replay.status_code, 202, replay.data)
        self.assertEqual(first.data["id"], replay.data["id"])
        self.assertEqual(first.headers["Idempotent-Replayed"], "false")
        self.assertEqual(replay.headers["Idempotent-Replayed"], "true")
        self.assertEqual(MapJob.objects.count(), 1)
        self.assertEqual(CreditTransaction.objects.count(), 1)
        delay.assert_called_once()
        self.account.refresh_from_db()
        self.assertEqual(self.account.available_balance, 4)
        self.assertEqual(self.account.reserved_balance, 1)

    @patch("apps.maps.tasks.process_map_job.delay")
    def test_idempotency_key_rejects_different_request(self, delay):
        delay.return_value = SimpleNamespace(id="celery-task-123")
        first = self.client.post(
            "/api/v1/map-jobs/",
            self.job_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY="request-conflict",
        )
        conflict = self.client.post(
            "/api/v1/map-jobs/",
            self.job_payload(date_to="2026-07-30"),
            format="json",
            HTTP_IDEMPOTENCY_KEY="request-conflict",
        )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.data["code"], "idempotency_conflict")
        self.assertEqual(MapJob.objects.count(), 1)
        self.assertEqual(CreditTransaction.objects.count(), 1)

    @patch("apps.maps.tasks.process_map_job.delay")
    def test_map_job_accepts_free_geometry_snapshot(self, delay):
        delay.return_value = SimpleNamespace(id="celery-free-geometry")
        payload = self.job_payload()
        payload.pop("property_id")
        payload["geometry"] = {
            "type": "Polygon",
            "coordinates": [
                [
                    [-48.01, -15.01],
                    [-48.01, -15.00],
                    [-48.00, -15.00],
                    [-48.00, -15.01],
                    [-48.01, -15.01],
                ]
            ],
        }

        response = self.client.post(
            "/api/v1/map-jobs/",
            payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY="free-geometry",
        )

        self.assertEqual(response.status_code, 202, response.data)
        self.assertIsNone(response.data["property_id"])
        self.assertEqual(response.data["geometry_snapshot"]["type"], "MultiPolygon")

    @patch("apps.maps.tasks.process_map_job.delay")
    def test_missing_processing_price_rejects_job_without_reserving(self, delay):
        self.price.delete()

        response = self.client.post(
            "/api/v1/map-jobs/",
            self.job_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY="missing-price",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "price_not_configured")
        self.assertEqual(MapJob.objects.count(), 0)
        self.assertEqual(CreditTransaction.objects.count(), 0)
        delay.assert_not_called()

    @patch("apps.maps.tasks.process_map_job.delay")
    def test_job_api_validates_xor_dates_and_insufficient_credits(self, delay):
        delay.return_value = SimpleNamespace(id="unused")
        both_sources = self.client.post(
            "/api/v1/map-jobs/",
            self.job_payload(
                geometry={
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            [
                                [-48.01, -15.01],
                                [-48.01, -15.00],
                                [-48.00, -15.01],
                                [-48.01, -15.01],
                            ]
                        ]
                    ],
                }
            ),
            format="json",
            HTTP_IDEMPOTENCY_KEY="invalid-xor",
        )
        invalid_dates = self.client.post(
            "/api/v1/map-jobs/",
            self.job_payload(date_from="2026-08-01", date_to="2026-07-01"),
            format="json",
            HTTP_IDEMPOTENCY_KEY="invalid-dates",
        )
        self.account.available_balance = 0
        self.account.save(update_fields=("available_balance", "updated_at"))
        insufficient = self.client.post(
            "/api/v1/map-jobs/",
            self.job_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY="insufficient",
        )

        self.assertEqual(both_sources.status_code, 400)
        self.assertEqual(invalid_dates.status_code, 400)
        self.assertEqual(insufficient.status_code, 402)
        self.assertEqual(MapJob.objects.count(), 0)

    @patch("apps.maps.tasks.process_map_job.delay")
    def test_queue_failure_marks_job_failed_and_releases_credit(self, delay):
        delay.side_effect = ConnectionError("Redis unavailable")

        response = self.client.post(
            "/api/v1/map-jobs/",
            self.job_payload(),
            format="json",
            HTTP_IDEMPOTENCY_KEY="queue-failure",
        )

        self.assertEqual(response.status_code, 503)
        job = MapJob.objects.get()
        self.assertEqual(job.status, MapJob.Status.FAILED)
        self.assertEqual(job.error_code, "QUEUE_UNAVAILABLE")
        self.account.refresh_from_db()
        self.assertEqual(self.account.available_balance, 5)
        self.assertEqual(self.account.reserved_balance, 0)
        self.assertEqual(CreditTransaction.objects.count(), 2)

    @patch("apps.maps.tasks.CopernicusSceneService.search_best_scene")
    @patch("apps.maps.tasks.process_scene_index")
    @patch("apps.maps.tasks.render_index_map")
    @patch("apps.maps.tasks.persist_generated_map")
    def test_ndvi_task_renders_persists_and_completes(
        self, persist_map, render_map, process_index, search
    ):
        search.return_value = CopernicusScene(
            item_id="sentinel-scene-123",
            acquired_at=datetime(2026, 7, 20, 13, tzinfo=timezone.utc),
            cloud_cover=Decimal("2.5"),
            assets={"B04": "red", "B08": "nir", "SCL": "scl"},
            collection="sentinel-2-l2a",
            platform="sentinel-2c",
        )
        process_index.return_value = PipelineProcessingResult(
            data=np.full((2, 2), 0.5, dtype=np.float32),
            valid_mask=np.ones((2, 2), dtype=bool),
            metadata={
                "valid_pixel_count": 4,
                "raster": {
                    "crs": "EPSG:32722",
                    "bounds": [500000, 8299980, 500020, 8300000],
                },
            },
        )
        render_map.return_value = SimpleNamespace()
        job = self.create_job()
        reserve_credits(
            map_job=job,
            amount=1,
            idempotency_key=f"map-job:{job.id}:reserve",
            created_by=self.user,
        )

        def complete_map(**kwargs):
            capture_reserved_credits(map_job=kwargs["job"], created_by=self.user)
            MapJob.objects.filter(pk=kwargs["job"].pk).update(
                status=MapJob.Status.COMPLETED,
                progress=100,
                current_step="Mapa concluído",
            )
            return SimpleNamespace(id="generated-map-123")

        persist_map.side_effect = complete_map
        first = process_map_job.apply(args=(str(job.id), self.tenant.schema_name)).get()
        second = process_map_job.apply(
            args=(str(job.id), self.tenant.schema_name)
        ).get()

        job.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(first, MapJob.Status.COMPLETED)
        self.assertEqual(second, MapJob.Status.COMPLETED)
        self.assertEqual(job.error_code, "")
        self.assertEqual(job.progress, 100)
        self.assertEqual(job.stac_item_id, "sentinel-scene-123")
        self.assertEqual(self.account.available_balance, 4)
        self.assertEqual(self.account.reserved_balance, 0)
        self.assertEqual(CreditTransaction.objects.count(), 2)
        search.assert_called_once()
        process_index.assert_called_once()
        render_map.assert_called_once()
        persist_map.assert_called_once()
        temporary_directory = process_index.call_args.kwargs["target_directory"]
        self.assertFalse(Path(temporary_directory).exists())

    @patch("apps.maps.tasks.CopernicusSceneService.search_best_scene")
    @patch("apps.maps.tasks.process_scene_index")
    @patch("apps.maps.tasks.render_index_map")
    def test_rendering_failure_releases_credit(self, render_map, process_index, search):
        search.return_value = CopernicusScene(
            item_id="sentinel-render-failure",
            acquired_at=datetime(2026, 7, 20, 13, tzinfo=timezone.utc),
            cloud_cover=Decimal("2.5"),
            assets={"B04": "red", "B08": "nir", "SCL": "scl"},
            collection="sentinel-2-l2a",
            platform="sentinel-2c",
        )
        process_index.return_value = PipelineProcessingResult(
            data=np.full((2, 2), 0.5, dtype=np.float32),
            valid_mask=np.ones((2, 2), dtype=bool),
            metadata={
                "valid_pixel_count": 4,
                "raster": {
                    "crs": "EPSG:32722",
                    "bounds": [500000, 8299980, 500020, 8300000],
                },
            },
        )
        render_map.side_effect = MapRenderingError("render failed")
        job = self.create_job()
        reserve_credits(
            map_job=job,
            amount=1,
            idempotency_key=f"map-job:{job.id}:reserve",
            created_by=self.user,
        )

        result = process_map_job.apply(
            args=(str(job.id), self.tenant.schema_name)
        ).get()

        job.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(result, MapJob.Status.FAILED)
        self.assertEqual(job.error_code, "MAP_RENDERING_ERROR")
        self.assertEqual(job.progress, 70)
        self.assertEqual(self.account.available_balance, 5)
        self.assertEqual(self.account.reserved_balance, 0)

    @patch("apps.maps.tasks.CopernicusSceneService.search_best_scene")
    @patch("apps.maps.tasks.process_scene_index")
    def test_missing_oauth_configuration_releases_credit(self, process_index, search):
        search.return_value = CopernicusScene(
            item_id="sentinel-scene-auth",
            acquired_at=datetime(2026, 7, 20, 13, tzinfo=timezone.utc),
            cloud_cover=Decimal("2.5"),
            assets={"B04": "red", "B08": "nir", "SCL": "scl"},
            collection="sentinel-2-l2a",
            platform="sentinel-2c",
        )
        process_index.side_effect = CopernicusConfigurationError("missing config")
        job = self.create_job()
        reserve_credits(
            map_job=job,
            amount=1,
            idempotency_key=f"map-job:{job.id}:reserve",
            created_by=self.user,
        )

        result = process_map_job.apply(
            args=(str(job.id), self.tenant.schema_name)
        ).get()

        job.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(result, MapJob.Status.FAILED)
        self.assertEqual(job.error_code, "COPERNICUS_AUTH_NOT_CONFIGURED")
        self.assertEqual(self.account.available_balance, 5)
        self.assertEqual(self.account.reserved_balance, 0)

    @override_settings(COPERNICUS_PROCESS_MAX_RETRIES=0)
    @patch("apps.maps.tasks.CopernicusSceneService.search_best_scene")
    @patch("apps.maps.tasks.process_scene_index")
    def test_exhausted_process_api_failure_releases_credit(self, process_index, search):
        search.return_value = CopernicusScene(
            item_id="sentinel-scene-unavailable",
            acquired_at=datetime(2026, 7, 20, 13, tzinfo=timezone.utc),
            cloud_cover=Decimal("2.5"),
            assets={"B04": "red", "B08": "nir", "SCL": "scl"},
            collection="sentinel-2-l2a",
            platform="sentinel-2c",
        )
        process_index.side_effect = SatelliteProcessUnavailable("unavailable")
        job = self.create_job()
        reserve_credits(
            map_job=job,
            amount=1,
            idempotency_key=f"map-job:{job.id}:reserve",
            created_by=self.user,
        )

        result = process_map_job.apply(
            args=(str(job.id), self.tenant.schema_name)
        ).get()

        job.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(result, MapJob.Status.FAILED)
        self.assertEqual(job.error_code, "SATELLITE_PROCESS_UNAVAILABLE")
        self.assertEqual(self.account.available_balance, 5)
        self.assertEqual(self.account.reserved_balance, 0)

    @patch("apps.maps.tasks.CopernicusSceneService.search_best_scene")
    def test_scene_search_without_results_releases_credit(self, search):
        search.side_effect = NoSatelliteSceneFound("no scene")
        job = self.create_job()
        reserve_credits(
            map_job=job,
            amount=1,
            idempotency_key=f"map-job:{job.id}:reserve",
            created_by=self.user,
        )

        result = process_map_job.apply(
            args=(str(job.id), self.tenant.schema_name)
        ).get()

        job.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(result, MapJob.Status.FAILED)
        self.assertEqual(job.error_code, "NO_SATELLITE_SCENE_FOUND")
        self.assertEqual(self.account.available_balance, 5)
        self.assertEqual(self.account.reserved_balance, 0)

    @override_settings(COPERNICUS_STAC_MAX_RETRIES=0)
    @patch("apps.maps.tasks.CopernicusSceneService.search_best_scene")
    def test_exhausted_catalog_failure_releases_credit(self, search):
        search.side_effect = SatelliteCatalogError("catalog unavailable")
        job = self.create_job()
        reserve_credits(
            map_job=job,
            amount=1,
            idempotency_key=f"map-job:{job.id}:reserve",
            created_by=self.user,
        )

        result = process_map_job.apply(
            args=(str(job.id), self.tenant.schema_name)
        ).get()

        job.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(result, MapJob.Status.FAILED)
        self.assertEqual(job.error_code, "SATELLITE_CATALOG_UNAVAILABLE")
        self.assertEqual(self.account.available_balance, 5)
        self.assertEqual(self.account.reserved_balance, 0)

    def test_billing_read_endpoints(self):
        account = self.client.get("/api/v1/billing/account/")
        transactions = self.client.get("/api/v1/billing/transactions/")
        prices = self.client.get("/api/v1/billing/prices/")

        self.assertEqual(account.status_code, 200)
        self.assertEqual(account.data["available_balance"], 5)
        self.assertEqual(transactions.status_code, 200)
        self.assertEqual(transactions.data["count"], 0)
        self.assertEqual(prices.status_code, 200)
        self.assertEqual(prices.data[0]["credit_cost"], 1)
