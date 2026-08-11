from __future__ import annotations

import posixpath
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.core.files.storage import Storage, default_storage
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.billing.services import release_reserved_credits

from ..models import GeneratedMap, MapJob


@dataclass(frozen=True)
class StalledJobsReport:
    candidates: tuple[UUID, ...]
    expired: tuple[UUID, ...]


@dataclass(frozen=True)
class MissingMapFile:
    generated_map_id: UUID
    field_name: str
    object_name: str


@dataclass(frozen=True)
class StorageReconciliationReport:
    expected_objects: int
    missing_files: tuple[MissingMapFile, ...]
    orphan_objects: tuple[str, ...]
    deleted_objects: tuple[str, ...]


def _stale_jobs_filter(stale_before: datetime) -> Q:
    return (
        Q(heartbeat_at__lt=stale_before)
        | Q(
            heartbeat_at__isnull=True,
            started_at__lt=stale_before,
        )
        | Q(
            heartbeat_at__isnull=True,
            started_at__isnull=True,
            created_at__lt=stale_before,
        )
    )


def _job_is_stale(job: MapJob, stale_before: datetime) -> bool:
    last_activity = job.heartbeat_at or job.started_at or job.created_at
    return (
        job.status not in MapJob.Status.terminal_values()
        and last_activity < stale_before
    )


def expire_stalled_jobs(
    *, stale_before: datetime, apply_changes: bool = False
) -> StalledJobsReport:
    active_jobs = MapJob.objects.exclude(status__in=MapJob.Status.terminal_values())
    candidate_ids = tuple(
        active_jobs.filter(_stale_jobs_filter(stale_before))
        .order_by("created_at")
        .values_list("id", flat=True)
    )
    if not apply_changes:
        return StalledJobsReport(candidates=candidate_ids, expired=())

    expired_ids: list[UUID] = []
    for job_id in candidate_ids:
        with transaction.atomic():
            job = MapJob.objects.select_for_update().get(pk=job_id)
            if not _job_is_stale(job, stale_before):
                continue

            release_reserved_credits(map_job=job, created_by=job.created_by)
            now = timezone.now()
            job.status = MapJob.Status.FAILED
            job.current_step = "Processamento expirado por inatividade"
            job.error_code = "JOB_STALLED"
            job.error_message = (
                "O processamento ficou sem atividade e foi encerrado. "
                "O crédito reservado foi devolvido."
            )
            job.finished_at = now
            job.heartbeat_at = now
            job.save(
                update_fields=(
                    "status",
                    "current_step",
                    "error_code",
                    "error_message",
                    "finished_at",
                    "heartbeat_at",
                )
            )
            expired_ids.append(job.id)

    return StalledJobsReport(
        candidates=candidate_ids,
        expired=tuple(expired_ids),
    )


def _walk_storage(storage: Storage, prefix: str) -> set[str]:
    objects: set[str] = set()
    pending = [prefix.rstrip("/")]
    while pending:
        directory = pending.pop()
        try:
            directories, files = storage.listdir(directory)
        except FileNotFoundError:
            continue
        objects.update(posixpath.join(directory, filename) for filename in files)
        pending.extend(posixpath.join(directory, name) for name in directories)
    return objects


def reconcile_generated_map_storage(
    *,
    storage: Storage | None = None,
    delete_orphans: bool = False,
) -> StorageReconciliationReport:
    storage = storage or default_storage
    expected: set[str] = set()
    missing: list[MissingMapFile] = []

    for generated_map in GeneratedMap.objects.only("id", "png_file", "pdf_file"):
        for field_name in ("png_file", "pdf_file"):
            object_name = getattr(generated_map, field_name).name or ""
            if object_name:
                expected.add(object_name)
            if not object_name or not storage.exists(object_name):
                missing.append(
                    MissingMapFile(
                        generated_map_id=generated_map.id,
                        field_name=field_name,
                        object_name=object_name,
                    )
                )

    tenant = getattr(connection, "tenant", None)
    tenant_id = getattr(tenant, "id", None)
    if tenant_id is None:
        raise RuntimeError("A reconciliação de storage exige um tenant ativo.")
    prefix = f"tenants/{tenant_id}/maps"
    stored_objects = _walk_storage(storage, prefix)
    orphan_objects = tuple(sorted(stored_objects - expected))

    deleted: list[str] = []
    if delete_orphans:
        for object_name in orphan_objects:
            storage.delete(object_name)
            deleted.append(object_name)

    return StorageReconciliationReport(
        expected_objects=len(expected),
        missing_files=tuple(missing),
        orphan_objects=orphan_objects,
        deleted_objects=tuple(deleted),
    )
