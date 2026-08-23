from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.db import connection
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context, tenant_context

from apps.tenants.models import Tenant

from .reconciliation import expire_stalled_jobs, reconcile_generated_map_storage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TenantReconciliationResult:
    tenant_id: UUID
    schema_name: str
    stalled_candidates: int = 0
    expired_jobs: int = 0
    expected_objects: int = 0
    missing_files: int = 0
    orphan_objects: int = 0
    deleted_objects: int = 0
    errors: tuple[str, ...] = ()

    @property
    def has_issues(self) -> bool:
        return bool(
            self.stalled_candidates
            or self.missing_files
            or self.orphan_objects
            or self.errors
        )


@dataclass(frozen=True)
class ReconciliationBatchReport:
    started_at: datetime
    finished_at: datetime
    tenants: tuple[TenantReconciliationResult, ...]
    skipped_locked: bool = False

    @property
    def totals(self) -> dict[str, int]:
        return {
            "tenant_count": len(self.tenants),
            "stalled_candidates": sum(item.stalled_candidates for item in self.tenants),
            "expired_jobs": sum(item.expired_jobs for item in self.tenants),
            "expected_objects": sum(item.expected_objects for item in self.tenants),
            "missing_files": sum(item.missing_files for item in self.tenants),
            "orphan_objects": sum(item.orphan_objects for item in self.tenants),
            "deleted_objects": sum(item.deleted_objects for item in self.tenants),
            "failed_tenants": sum(bool(item.errors) for item in self.tenants),
        }

    @property
    def has_issues(self) -> bool:
        return any(item.has_issues for item in self.tenants)


def _try_acquire_reconciliation_lock() -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s)",
            [settings.MAP_RECONCILIATION_LOCK_ID],
        )
        return bool(cursor.fetchone()[0])


def _release_reconciliation_lock() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_unlock(%s)",
            [settings.MAP_RECONCILIATION_LOCK_ID],
        )


def _reconcile_tenant(
    tenant: Tenant,
    *,
    stale_before: datetime,
    apply_stalled: bool,
    delete_orphans: bool,
) -> TenantReconciliationResult:
    errors: list[str] = []
    stalled_candidates = 0
    expired_jobs = 0
    expected_objects = 0
    missing_files = 0
    orphan_objects = 0
    deleted_objects = 0

    with tenant_context(tenant):
        try:
            stalled = expire_stalled_jobs(
                stale_before=stale_before,
                apply_changes=apply_stalled,
            )
            stalled_candidates = len(stalled.candidates)
            expired_jobs = len(stalled.expired)
        except Exception as exc:
            errors.append(f"jobs:{type(exc).__name__}")
            logger.exception(
                "Scheduled stalled-job reconciliation failed",
                extra={"tenant_id": tenant.id},
            )

        try:
            storage = reconcile_generated_map_storage(
                delete_orphans=delete_orphans,
            )
            expected_objects = storage.expected_objects
            missing_files = len(storage.missing_files)
            orphan_objects = len(storage.orphan_objects)
            deleted_objects = len(storage.deleted_objects)
        except Exception as exc:
            errors.append(f"storage:{type(exc).__name__}")
            logger.exception(
                "Scheduled storage reconciliation failed",
                extra={"tenant_id": tenant.id},
            )

    return TenantReconciliationResult(
        tenant_id=tenant.id,
        schema_name=tenant.schema_name,
        stalled_candidates=stalled_candidates,
        expired_jobs=expired_jobs,
        expected_objects=expected_objects,
        missing_files=missing_files,
        orphan_objects=orphan_objects,
        deleted_objects=deleted_objects,
        errors=tuple(errors),
    )


def reconcile_all_tenants() -> ReconciliationBatchReport:
    started_at = timezone.now()
    public_schema = get_public_schema_name()

    with schema_context(public_schema):
        if not _try_acquire_reconciliation_lock():
            return ReconciliationBatchReport(
                started_at=started_at,
                finished_at=timezone.now(),
                tenants=(),
                skipped_locked=True,
            )

        try:
            tenants = tuple(
                Tenant.objects.exclude(schema_name=public_schema).order_by(
                    "schema_name"
                )
            )
            stale_before = timezone.now() - timedelta(
                minutes=settings.MAP_JOB_STALE_MINUTES
            )
            results = tuple(
                _reconcile_tenant(
                    tenant,
                    stale_before=stale_before,
                    apply_stalled=settings.MAP_RECONCILIATION_APPLY_STALLED,
                    delete_orphans=settings.MAP_RECONCILIATION_DELETE_ORPHANS,
                )
                for tenant in tenants
            )
        finally:
            _release_reconciliation_lock()

    return ReconciliationBatchReport(
        started_at=started_at,
        finished_at=timezone.now(),
        tenants=results,
    )
