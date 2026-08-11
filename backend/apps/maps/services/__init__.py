from __future__ import annotations

import hashlib
import json
import logging

from django.db import connection, transaction
from django.utils import timezone

from apps.billing.services import (
    get_processing_cost,
    lock_credit_account,
    release_reserved_credits,
    reserve_credits,
)

from ..exceptions import MapJobEnqueueError, MapJobIdempotencyConflict
from ..models import MapJob

logger = logging.getLogger(__name__)


def _request_fingerprint(
    *,
    created_by,
    index_type: str,
    geometry_snapshot,
    property_instance,
    requested_scene_date,
    date_from,
    date_to,
    max_cloud_cover,
    reprocessed_from=None,
) -> str:
    payload = {
        "user_id": str(created_by.id),
        "index_type": index_type,
        "geometry": geometry_snapshot.ewkt,
        "property_id": str(property_instance.id) if property_instance else None,
        "requested_scene_date": (
            str(requested_scene_date) if requested_scene_date else None
        ),
        "date_from": str(date_from) if date_from else None,
        "date_to": str(date_to) if date_to else None,
        "max_cloud_cover": str(max_cloud_cover),
    }
    if reprocessed_from:
        payload["reprocessed_from_id"] = str(reprocessed_from.id)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def _compensate_enqueue_failure(job_id) -> None:
    with transaction.atomic():
        job = MapJob.objects.select_for_update().get(pk=job_id)
        if job.status in MapJob.Status.terminal_values():
            return
        release_reserved_credits(map_job=job, created_by=job.created_by)
        job.status = MapJob.Status.FAILED
        job.progress = 0
        job.current_step = "Falha ao enfileirar processamento"
        job.error_code = "QUEUE_UNAVAILABLE"
        job.error_message = (
            "Não foi possível iniciar o processamento. Tente novamente mais tarde."
        )
        job.finished_at = timezone.now()
        job.heartbeat_at = job.finished_at
        job.save(
            update_fields=(
                "status",
                "progress",
                "current_step",
                "error_code",
                "error_message",
                "finished_at",
                "heartbeat_at",
            )
        )


def create_map_job(
    *,
    created_by,
    idempotency_key: str,
    index_type: str,
    geometry_snapshot,
    property_instance=None,
    requested_scene_date=None,
    date_from=None,
    date_to=None,
    max_cloud_cover=20,
    reprocessed_from=None,
) -> tuple[MapJob, bool]:
    fingerprint = _request_fingerprint(
        created_by=created_by,
        index_type=index_type,
        geometry_snapshot=geometry_snapshot,
        property_instance=property_instance,
        requested_scene_date=requested_scene_date,
        date_from=date_from,
        date_to=date_to,
        max_cloud_cover=max_cloud_cover,
        reprocessed_from=reprocessed_from,
    )
    schema_name = connection.schema_name

    with transaction.atomic():
        # One account per tenant is a deliberately coarse MVP lock. It serializes
        # reservations and closes the race between duplicate HTTP requests.
        lock_credit_account()
        existing = (
            MapJob.objects.select_for_update()
            .filter(request_idempotency_key=idempotency_key)
            .first()
        )
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise MapJobIdempotencyConflict(
                    "A Idempotency-Key já foi usada para outra solicitação."
                )
            return existing, True

        cost = get_processing_cost(index_type)
        job = MapJob.objects.create(
            status=MapJob.Status.PENDING,
            progress=0,
            current_step="Aguardando processamento",
            heartbeat_at=timezone.now(),
            index_type=index_type,
            geometry_snapshot=geometry_snapshot,
            property=property_instance,
            requested_scene_date=requested_scene_date,
            date_from=date_from,
            date_to=date_to,
            max_cloud_cover=max_cloud_cover,
            credit_cost=cost,
            request_idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            created_by=created_by,
            reprocessed_from=reprocessed_from,
        )
        reserve_credits(
            map_job=job,
            amount=cost,
            idempotency_key=f"map-job:{job.id}:reserve",
            created_by=created_by,
        )

    from ..tasks import process_map_job

    try:
        async_result = process_map_job.delay(str(job.id), schema_name)
    except Exception as exc:
        logger.exception(
            "Failed to enqueue map job",
            extra={"job_id": job.id, "user_id": created_by.id},
        )
        _compensate_enqueue_failure(job.id)
        raise MapJobEnqueueError(
            "Não foi possível enfileirar o processamento."
        ) from exc

    MapJob.objects.filter(pk=job.pk).update(celery_task_id=async_result.id)
    job.refresh_from_db()
    return job, False
