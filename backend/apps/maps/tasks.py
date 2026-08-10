import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.billing.services import release_reserved_credits

from .exceptions import NoSatelliteSceneFound, SatelliteCatalogError
from .models import MapJob
from .services.copernicus import CopernicusScene, CopernicusSceneService

logger = logging.getLogger(__name__)


@shared_task(name="maps.healthcheck")
def healthcheck() -> str:
    return "ok"


def _start_scene_search(job_id: str, celery_task_id: str | None) -> MapJob:
    with transaction.atomic():
        job = MapJob.objects.select_for_update().get(pk=job_id)
        if job.status in {MapJob.Status.COMPLETED, MapJob.Status.FAILED}:
            return job
        job.status = MapJob.Status.SEARCHING_SCENE
        job.progress = 5
        job.current_step = "Pesquisando cenas Sentinel-2 L2A"
        job.celery_task_id = celery_task_id or job.celery_task_id
        job.started_at = job.started_at or timezone.now()
        job.error_code = ""
        job.error_message = ""
        job.save(
            update_fields=(
                "status",
                "progress",
                "current_step",
                "celery_task_id",
                "started_at",
                "error_code",
                "error_message",
            )
        )
        return job


def _fail_job(
    *,
    job_id: str,
    error_code: str,
    error_message: str,
    current_step: str,
    progress: int,
    scene: CopernicusScene | None = None,
) -> str:
    with transaction.atomic():
        job = MapJob.objects.select_for_update().get(pk=job_id)
        if job.status in {MapJob.Status.COMPLETED, MapJob.Status.FAILED}:
            return job.status

        release_reserved_credits(map_job=job, created_by=job.created_by)
        job.status = MapJob.Status.FAILED
        job.progress = progress
        job.current_step = current_step
        job.error_code = error_code
        job.error_message = error_message
        job.finished_at = timezone.now()
        update_fields = [
            "status",
            "progress",
            "current_step",
            "error_code",
            "error_message",
            "finished_at",
        ]
        if scene:
            job.stac_item_id = scene.item_id
            update_fields.append("stac_item_id")
        job.save(update_fields=update_fields)
        return job.status


@shared_task(bind=True, name="maps.process_map_job")
def process_map_job(self, job_id: str, schema_name: str) -> str:
    with schema_context(schema_name):
        job = _start_scene_search(job_id, self.request.id)
        if job.status in {MapJob.Status.COMPLETED, MapJob.Status.FAILED}:
            return job.status

        try:
            scene = CopernicusSceneService().search_best_scene(
                geometry=job.geometry_snapshot,
                requested_scene_date=job.requested_scene_date,
                date_from=job.date_from,
                date_to=job.date_to,
                max_cloud_cover=job.max_cloud_cover,
            )
        except NoSatelliteSceneFound:
            logger.info(
                "No compatible satellite scene found",
                extra={"job_id": job.id, "user_id": job.created_by_id},
            )
            return _fail_job(
                job_id=job_id,
                error_code="NO_SATELLITE_SCENE_FOUND",
                error_message=(
                    "Nenhuma cena compatível foi encontrada para a área e período."
                ),
                current_step="Nenhuma cena disponível",
                progress=5,
            )
        except SatelliteCatalogError as exc:
            logger.warning(
                "Satellite catalog request failed",
                exc_info=True,
                extra={"job_id": job.id, "user_id": job.created_by_id},
            )
            if self.request.retries < settings.COPERNICUS_STAC_MAX_RETRIES:
                raise self.retry(
                    exc=exc,
                    countdown=settings.COPERNICUS_STAC_RETRY_DELAY_SECONDS,
                    max_retries=settings.COPERNICUS_STAC_MAX_RETRIES,
                )
            return _fail_job(
                job_id=job_id,
                error_code="SATELLITE_CATALOG_UNAVAILABLE",
                error_message=(
                    "O catálogo de imagens está temporariamente indisponível. "
                    "Tente novamente mais tarde."
                ),
                current_step="Falha ao consultar catálogo",
                progress=5,
            )

        logger.info(
            "Satellite scene selected",
            extra={
                "job_id": job.id,
                "user_id": job.created_by_id,
                "stac_item_id": scene.item_id,
            },
        )
        return _fail_job(
            job_id=job_id,
            error_code="PIPELINE_NOT_IMPLEMENTED",
            error_message=(
                "Uma cena Sentinel-2 foi selecionada, mas o download e o "
                "processamento ainda não estão disponíveis. O crédito foi liberado."
            ),
            current_step="Cena selecionada; processamento ainda não disponível",
            progress=15,
            scene=scene,
        )
