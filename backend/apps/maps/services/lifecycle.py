from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.billing.services import release_reserved_credits

from ..exceptions import MapJobTransitionConflict
from ..models import MapJob
from . import create_map_job


@transaction.atomic
def cancel_map_job(*, job_id, cancelled_by) -> tuple[MapJob, bool]:
    job = MapJob.objects.select_for_update().get(pk=job_id)
    if job.status == MapJob.Status.CANCELLED:
        return job, True
    if job.status in {MapJob.Status.COMPLETED, MapJob.Status.FAILED}:
        raise MapJobTransitionConflict(
            "Somente processamentos ainda ativos podem ser cancelados."
        )

    release_reserved_credits(map_job=job, created_by=cancelled_by)
    job.status = MapJob.Status.CANCELLED
    job.current_step = "Processamento cancelado"
    job.error_code = ""
    job.error_message = ""
    job.finished_at = timezone.now()
    job.heartbeat_at = job.finished_at
    job.cancelled_at = job.finished_at
    job.cancelled_by = cancelled_by
    job.save(
        update_fields=(
            "status",
            "current_step",
            "error_code",
            "error_message",
            "finished_at",
            "heartbeat_at",
            "cancelled_at",
            "cancelled_by",
        )
    )
    return job, False


def reprocess_map_job(
    *, source_job: MapJob, created_by, idempotency_key: str
) -> tuple[MapJob, bool]:
    if source_job.status not in MapJob.Status.terminal_values():
        raise MapJobTransitionConflict(
            "Somente processamentos concluídos, com falha ou cancelados podem ser reprocessados."
        )
    return create_map_job(
        created_by=created_by,
        idempotency_key=idempotency_key,
        index_type=source_job.index_type,
        geometry_snapshot=source_job.geometry_snapshot.clone(),
        property_instance=source_job.property,
        requested_scene_date=source_job.requested_scene_date,
        date_from=source_job.date_from,
        date_to=source_job.date_to,
        max_cloud_cover=source_job.max_cloud_cover,
        reprocessed_from=source_job,
    )
