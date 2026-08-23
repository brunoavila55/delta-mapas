from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.db import connection
from django.test import Client, override_settings
from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import Membership
from apps.billing.models import CreditAccount, CreditTransaction
from apps.billing.services import reserve_credits
from apps.maps.models import GeneratedMap, MapJob
from apps.maps.exceptions import MapJobCancelled
from apps.maps.services.copernicus import CopernicusScene
from apps.maps.services.lifecycle import cancel_map_job
from apps.maps.services.products import persist_generated_map
from apps.maps.services.rendering import RenderedMapFiles
from apps.properties.models import Property


@override_settings(SECRET_KEY="test-secret-key-with-at-least-thirty-two-bytes")
class GeneratedMapProductTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Tenant de mapas gerados"
        return tenant

    @staticmethod
    def get_test_schema_name():
        return "test_generated_maps"

    @staticmethod
    def get_test_tenant_domain():
        return "generated-maps.test.localhost"

    def setUp(self):
        super().setUp()
        connection.set_tenant(self.tenant)
        self.temporary_media = TemporaryDirectory()
        self.storage_override = override_settings(
            MEDIA_ROOT=self.temporary_media.name,
            STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                },
            },
        )
        self.storage_override.enable()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="generated-map-user",
            password="test-password-123",
        )
        Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            role=Membership.Role.OWNER,
        )
        self.client = Client(HTTP_HOST=self.get_test_tenant_domain())
        self.client.force_login(self.user)
        self.account = CreditAccount.objects.create(
            singleton_key=True,
            available_balance=5,
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
            name="Fazenda Produto",
            geometry=self.geometry,
            created_by=self.user,
        )
        self.job = MapJob.objects.create(
            geometry_snapshot=self.geometry,
            property=self.property,
            date_from="2026-07-01",
            date_to="2026-07-31",
            created_by=self.user,
        )
        reserve_credits(
            map_job=self.job,
            amount=1,
            idempotency_key=f"map-job:{self.job.id}:reserve",
            created_by=self.user,
        )
        self.scene = CopernicusScene(
            item_id="sentinel-product-scene",
            acquired_at=datetime(2026, 7, 20, 13, tzinfo=timezone.utc),
            cloud_cover=Decimal("2.5"),
            assets={"B04": "red", "B08": "nir", "SCL": "scl"},
            collection="sentinel-2-l2a",
            platform="sentinel-2c",
        )

    def tearDown(self):
        self.storage_override.disable()
        self.temporary_media.cleanup()
        super().tearDown()

    def _rendered_files(self, directory: Path) -> RenderedMapFiles:
        directory.mkdir(parents=True, exist_ok=True)
        png_path = directory / "map.png"
        pdf_path = directory / "map.pdf"
        png_path.write_bytes(b"\x89PNG\r\nproduct")
        pdf_path.write_bytes(b"%PDF-1.7\nproduct")
        return RenderedMapFiles(
            png_path=png_path,
            pdf_path=pdf_path,
            metadata={"renderer": "test", "template": "test-v1"},
        )

    def test_persists_files_completes_job_and_captures_credit_once(self):
        source = Path(self.temporary_media.name) / "source"
        rendered = self._rendered_files(source)

        generated = persist_generated_map(
            job=self.job,
            scene=self.scene,
            rendered=rendered,
            pipeline_metadata={"index": "NDVI", "valid_pixel_count": 10},
        )
        replay = persist_generated_map(
            job=self.job,
            scene=self.scene,
            rendered=rendered,
            pipeline_metadata={"index": "NDVI", "valid_pixel_count": 10},
        )

        self.job.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(generated.id, replay.id)
        self.assertEqual(GeneratedMap.objects.count(), 1)
        self.assertEqual(self.job.status, MapJob.Status.COMPLETED)
        self.assertEqual(self.job.progress, 100)
        self.assertEqual(self.account.available_balance, 4)
        self.assertEqual(self.account.reserved_balance, 0)
        self.assertEqual(CreditTransaction.objects.count(), 2)
        self.assertEqual(generated.metadata["cloud_mask"], "SCL")
        self.assertTrue(generated.png_file.storage.exists(generated.png_file.name))
        self.assertTrue(generated.pdf_file.storage.exists(generated.pdf_file.name))

    def test_cancelled_job_cannot_persist_or_capture_products(self):
        rendered = self._rendered_files(
            Path(self.temporary_media.name) / "cancelled-source"
        )
        cancel_map_job(job_id=self.job.id, cancelled_by=self.user)

        with self.assertRaises(MapJobCancelled):
            persist_generated_map(
                job=self.job,
                scene=self.scene,
                rendered=rendered,
                pipeline_metadata={"index": "NDVI"},
            )

        self.job.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(self.job.status, MapJob.Status.CANCELLED)
        self.assertEqual(GeneratedMap.objects.count(), 0)
        self.assertEqual(self.account.available_balance, 5)
        self.assertEqual(self.account.reserved_balance, 0)
        self.assertFalse(
            CreditTransaction.objects.filter(
                map_job=self.job,
                transaction_type=CreditTransaction.Type.CAPTURE,
            ).exists()
        )

    def test_web_lists_and_downloads_private_products(self):
        generated = persist_generated_map(
            job=self.job,
            scene=self.scene,
            rendered=self._rendered_files(Path(self.temporary_media.name) / "source"),
            pipeline_metadata={"index": "NDVI"},
        )

        listing = self.client.get(f"/maps/?search={self.scene.item_id}")
        png = self.client.get(f"/maps/{generated.id}/png/")
        pdf = self.client.get(f"/maps/{generated.id}/pdf/")

        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, self.property.name)
        self.assertContains(listing, f"/maps/{generated.id}/png/")
        self.assertEqual(png.status_code, 200)
        self.assertEqual(png["Content-Type"], "image/png")
        self.assertTrue(b"".join(png.streaming_content).startswith(b"\x89PNG"))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(b"".join(pdf.streaming_content).startswith(b"%PDF"))
