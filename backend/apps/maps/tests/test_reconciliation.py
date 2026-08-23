from datetime import timedelta
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection
from django.test import override_settings
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import Membership
from apps.billing.models import CreditAccount, CreditTransaction
from apps.billing.services import reserve_credits
from apps.maps.models import GeneratedMap, MapJob
from apps.maps.services.reconciliation import (
    expire_stalled_jobs,
    reconcile_generated_map_storage,
)
from apps.maps.services.operations import reconcile_all_tenants
from apps.properties.models import Property


class MapReconciliationTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Tenant de reconciliação"
        return tenant

    @staticmethod
    def get_test_schema_name():
        return "test_map_reconciliation"

    @staticmethod
    def get_test_tenant_domain():
        return "map-reconciliation.test.localhost"

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
            username="reconciliation-user",
            password="test-password-123",
        )
        Membership.objects.create(
            user=self.user,
            tenant=self.tenant,
            role=Membership.Role.OWNER,
        )
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
            name="Fazenda Reconciliação",
            geometry=self.geometry,
            created_by=self.user,
        )

    def tearDown(self):
        self.storage_override.disable()
        self.temporary_media.cleanup()
        super().tearDown()

    def _job(self, *, heartbeat_at=None, status=MapJob.Status.PROCESSING):
        return MapJob.objects.create(
            status=status,
            progress=50,
            current_step="Calculando NDVI",
            heartbeat_at=heartbeat_at,
            geometry_snapshot=self.geometry,
            property=self.property,
            date_from="2026-07-01",
            date_to="2026-07-31",
            created_by=self.user,
        )

    def test_dry_run_reports_stalled_job_without_changing_credit_or_status(self):
        job = self._job(heartbeat_at=timezone.now() - timedelta(hours=3))
        reserve_credits(
            map_job=job,
            amount=1,
            idempotency_key=f"map-job:{job.id}:reserve",
            created_by=self.user,
        )

        report = expire_stalled_jobs(
            stale_before=timezone.now() - timedelta(hours=2),
        )

        job.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(report.candidates, (job.id,))
        self.assertEqual(report.expired, ())
        self.assertEqual(job.status, MapJob.Status.PROCESSING)
        self.assertEqual(self.account.available_balance, 4)
        self.assertEqual(self.account.reserved_balance, 1)

    def test_apply_expires_only_stalled_jobs_and_releases_credit_once(self):
        stale = self._job(heartbeat_at=timezone.now() - timedelta(hours=3))
        fresh = self._job(heartbeat_at=timezone.now())
        reserve_credits(
            map_job=stale,
            amount=1,
            idempotency_key=f"map-job:{stale.id}:reserve",
            created_by=self.user,
        )

        report = expire_stalled_jobs(
            stale_before=timezone.now() - timedelta(hours=2),
            apply_changes=True,
        )
        replay = expire_stalled_jobs(
            stale_before=timezone.now() - timedelta(hours=2),
            apply_changes=True,
        )

        stale.refresh_from_db()
        fresh.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(report.expired, (stale.id,))
        self.assertEqual(replay.expired, ())
        self.assertEqual(stale.status, MapJob.Status.FAILED)
        self.assertEqual(stale.error_code, "JOB_STALLED")
        self.assertEqual(fresh.status, MapJob.Status.PROCESSING)
        self.assertEqual(self.account.available_balance, 5)
        self.assertEqual(self.account.reserved_balance, 0)
        self.assertEqual(
            CreditTransaction.objects.filter(
                map_job=stale,
                transaction_type=CreditTransaction.Type.RELEASE,
            ).count(),
            1,
        )

    def test_storage_audit_reports_missing_and_deletes_orphan_only_when_requested(self):
        job = self._job(status=MapJob.Status.COMPLETED)
        prefix = f"tenants/{self.tenant.id}/maps/2026/08/{job.id}"
        png_name = f"{prefix}/map.png"
        pdf_name = f"{prefix}/map.pdf"
        generated_map = GeneratedMap.objects.create(
            job=job,
            property=self.property,
            index_type="NDVI",
            geometry_snapshot=self.geometry,
            scene_date=timezone.now(),
            stac_item_id="reconciliation-scene",
            png_file=png_name,
            pdf_file=pdf_name,
            created_by=self.user,
        )
        default_storage.save(png_name, ContentFile(b"png"))
        default_storage.save(pdf_name, ContentFile(b"pdf"))
        orphan_name = f"tenants/{self.tenant.id}/maps/orphan.png"
        default_storage.save(orphan_name, ContentFile(b"orphan"))

        dry_run = reconcile_generated_map_storage()
        self.assertEqual(dry_run.expected_objects, 2)
        self.assertEqual(dry_run.missing_files, ())
        self.assertEqual(dry_run.orphan_objects, (orphan_name,))
        self.assertTrue(default_storage.exists(orphan_name))

        deleted = reconcile_generated_map_storage(delete_orphans=True)
        self.assertEqual(deleted.deleted_objects, (orphan_name,))
        self.assertFalse(default_storage.exists(orphan_name))

        default_storage.delete(pdf_name)
        missing = reconcile_generated_map_storage()
        self.assertEqual(len(missing.missing_files), 1)
        self.assertEqual(missing.missing_files[0].generated_map_id, generated_map.id)
        self.assertEqual(missing.missing_files[0].field_name, "pdf_file")

    @override_settings(
        MAP_RECONCILIATION_APPLY_STALLED=True,
        MAP_RECONCILIATION_DELETE_ORPHANS=False,
        MAP_JOB_STALE_MINUTES=120,
    )
    def test_scheduled_reconciliation_runs_all_tenants_and_expires_stalled_job(self):
        job = self._job(heartbeat_at=timezone.now() - timedelta(hours=3))
        reserve_credits(
            map_job=job,
            amount=1,
            idempotency_key=f"map-job:{job.id}:reserve",
            created_by=self.user,
        )

        report = reconcile_all_tenants()

        job.refresh_from_db()
        tenant_report = next(
            item for item in report.tenants if item.tenant_id == self.tenant.id
        )
        self.assertFalse(report.skipped_locked)
        self.assertEqual(tenant_report.stalled_candidates, 1)
        self.assertEqual(tenant_report.expired_jobs, 1)
        self.assertEqual(tenant_report.errors, ())
        self.assertEqual(job.status, MapJob.Status.FAILED)
        self.assertEqual(job.error_code, "JOB_STALLED")
