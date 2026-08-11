from __future__ import annotations

import logging

from django.core.files import File
from django.db import transaction
from django.utils import timezone

from apps.billing.services import capture_reserved_credits

from ..exceptions import MapFinalizationError, MapJobCancelled, StorageUploadError
from ..models import GeneratedMap, MapJob
from .copernicus import CopernicusScene
from .rendering import RenderedMapFiles

logger = logging.getLogger(__name__)


def _delete_uploaded_files(generated_map: GeneratedMap) -> None:
    for field in (generated_map.png_file, generated_map.pdf_file):
        if not field.name:
            continue
        try:
            field.storage.delete(field.name)
        except Exception:
            logger.exception(
                "Failed to clean uploaded generated map object",
                extra={"generated_map_id": generated_map.id},
            )


def persist_generated_map(
    *,
    job: MapJob,
    scene: CopernicusScene,
    rendered: RenderedMapFiles,
    pipeline_metadata: dict[str, object],
) -> GeneratedMap:
    metadata = {
        **pipeline_metadata,
        **rendered.metadata,
        "satellite": "Sentinel-2",
        "product_level": "L2A",
        "collection": scene.collection,
        "platform": scene.platform,
        "bands": ["B04", "B08"],
        "cloud_mask": "SCL",
    }
    generated_map = GeneratedMap(
        job=job,
        property=job.property,
        index_type=job.index_type,
        geometry_snapshot=job.geometry_snapshot,
        scene_date=scene.acquired_at,
        stac_item_id=scene.item_id,
        cloud_cover=scene.cloud_cover,
        metadata=metadata,
        created_by=job.created_by,
    )

    try:
        with rendered.png_path.open("rb") as png_stream:
            generated_map.png_file.save("map.png", File(png_stream), save=False)
        with rendered.pdf_path.open("rb") as pdf_stream:
            generated_map.pdf_file.save("map.pdf", File(pdf_stream), save=False)
    except Exception as exc:
        _delete_uploaded_files(generated_map)
        raise StorageUploadError(
            "Não foi possível armazenar os produtos cartográficos."
        ) from exc

    try:
        with transaction.atomic():
            locked_job = MapJob.objects.select_for_update().get(pk=job.pk)
            if locked_job.status == MapJob.Status.CANCELLED:
                raise MapJobCancelled(
                    "O processamento foi cancelado antes da finalização."
                )
            existing = GeneratedMap.objects.filter(job=locked_job).first()
            if existing:
                if locked_job.status != MapJob.Status.COMPLETED:
                    capture_reserved_credits(
                        map_job=locked_job,
                        created_by=locked_job.created_by,
                    )
                    locked_job.status = MapJob.Status.COMPLETED
                    locked_job.progress = 100
                    locked_job.current_step = "Mapa concluído"
                    locked_job.error_code = ""
                    locked_job.error_message = ""
                    locked_job.finished_at = locked_job.finished_at or timezone.now()
                    locked_job.heartbeat_at = locked_job.finished_at
                    locked_job.save(
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
            else:
                generated_map.job = locked_job
                generated_map.save()
                capture_reserved_credits(
                    map_job=locked_job,
                    created_by=locked_job.created_by,
                )
                locked_job.status = MapJob.Status.COMPLETED
                locked_job.progress = 100
                locked_job.current_step = "Mapa concluído"
                locked_job.error_code = ""
                locked_job.error_message = ""
                locked_job.finished_at = timezone.now()
                locked_job.heartbeat_at = locked_job.finished_at
                locked_job.save(
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
    except MapJobCancelled:
        _delete_uploaded_files(generated_map)
        raise
    except Exception as exc:
        _delete_uploaded_files(generated_map)
        raise MapFinalizationError(
            "Não foi possível finalizar o mapa e a cobrança."
        ) from exc

    if existing:
        _delete_uploaded_files(generated_map)
        return existing
    return generated_map
