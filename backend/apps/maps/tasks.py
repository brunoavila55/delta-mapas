import logging
from tempfile import TemporaryDirectory

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.billing.services import release_reserved_credits
from apps.properties.services import calculate_area_hectares

from .exceptions import (
    CopernicusAuthenticationUnavailable,
    MapJobCancelled,
    NoSatelliteSceneFound,
    PipelineStepFailure,
    SatelliteCatalogError,
    SatelliteProcessUnavailable,
)
from .models import MapJob
from .services.copernicus import CopernicusScene, CopernicusSceneService
from .services.alerts import (
    build_reconciliation_alert,
    build_reconciliation_failure_alert,
    deliver_operations_alert,
)
from .services.operations import reconcile_all_tenants as run_reconciliation
from .services.pipeline import process_scene_index
from .services.products import persist_generated_map
from .services.rendering import render_index_map

logger = logging.getLogger(__name__)


@shared_task(name="maps.healthcheck")
def healthcheck() -> str:
    return "ok"


@shared_task(name="maps.reconcile_all_tenants")
def reconcile_all_tenants() -> dict:
    try:
        report = run_reconciliation()
    except Exception as exc:
        payload = build_reconciliation_failure_alert(type(exc).__name__)
        delivery = deliver_operations_alert(payload)
        logger.exception(
            "Scheduled map reconciliation failed",
            extra={
                "alert_type": payload["event"],
                "alert_delivery": delivery.status,
            },
        )
        raise

    if report.skipped_locked:
        logger.info(
            "Scheduled map reconciliation skipped because another run is active"
        )
        return {"status": "skipped_locked"}

    totals = report.totals
    payload = build_reconciliation_alert(report)
    delivery = deliver_operations_alert(payload) if payload else None
    log_extra = {
        "tenant_count": totals["tenant_count"],
        "expired_jobs": totals["expired_jobs"],
        "missing_files": totals["missing_files"],
        "orphan_objects": totals["orphan_objects"],
        "failed_tenants": totals["failed_tenants"],
    }
    if payload and delivery:
        log_extra.update(
            {
                "alert_type": payload["event"],
                "alert_delivery": delivery.status,
            }
        )
        logger.warning("Scheduled map reconciliation found anomalies", extra=log_extra)
    else:
        logger.info("Scheduled map reconciliation completed", extra=log_extra)

    return {
        "status": "issues" if payload else "ok",
        "totals": totals,
        "alert_delivery": delivery.status if delivery else "not_required",
    }


def _start_scene_search(job_id: str, celery_task_id: str | None) -> MapJob:
    with transaction.atomic():
        job = MapJob.objects.select_for_update().get(pk=job_id)
        if job.status in MapJob.Status.terminal_values():
            return job
        job.status = MapJob.Status.SEARCHING_SCENE
        job.progress = 5
        job.current_step = "Pesquisando cenas Sentinel-2 L2A"
        job.celery_task_id = celery_task_id or job.celery_task_id
        job.heartbeat_at = timezone.now()
        job.started_at = job.started_at or job.heartbeat_at
        job.error_code = ""
        job.error_message = ""
        job.save(
            update_fields=(
                "status",
                "progress",
                "current_step",
                "celery_task_id",
                "heartbeat_at",
                "started_at",
                "error_code",
                "error_message",
            )
        )
        return job


def _update_job_status(
    *,
    job_id: str,
    status: str,
    progress: int,
    current_step: str,
    scene: CopernicusScene | None = None,
) -> bool:
    with transaction.atomic():
        job = MapJob.objects.select_for_update().get(pk=job_id)
        if job.status in MapJob.Status.terminal_values():
            return False
        job.status = status
        job.progress = progress
        job.current_step = current_step
        job.heartbeat_at = timezone.now()
        update_fields = ["status", "progress", "current_step", "heartbeat_at"]
        if scene:
            job.stac_item_id = scene.item_id
            update_fields.append("stac_item_id")
        job.save(update_fields=update_fields)
        return True


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
        if job.status in MapJob.Status.terminal_values():
            return job.status

        release_reserved_credits(map_job=job, created_by=job.created_by)
        job.status = MapJob.Status.FAILED
        job.progress = progress
        job.current_step = current_step
        job.error_code = error_code
        job.error_message = error_message
        job.finished_at = timezone.now()
        job.heartbeat_at = job.finished_at
        update_fields = [
            "status",
            "progress",
            "current_step",
            "error_code",
            "error_message",
            "finished_at",
            "heartbeat_at",
        ]
        if scene:
            job.stac_item_id = scene.item_id
            update_fields.append("stac_item_id")
        job.save(update_fields=update_fields)
        return job.status


def _pipeline_status_callback(job_id: str, stage: str) -> None:
    stages = {
        "PREPROCESSING": (
            MapJob.Status.PREPROCESSING,
            35,
            "Validando e alinhando bandas Sentinel-2",
        ),
        "PROCESSING": (
            MapJob.Status.PROCESSING,
            50,
            "Aplicando máscara SCL e calculando NDVI",
        ),
    }
    status, progress, current_step = stages[stage]
    updated = _update_job_status(
        job_id=job_id,
        status=status,
        progress=progress,
        current_step=current_step,
    )
    if not updated:
        raise MapJobCancelled("O processamento foi cancelado.")


@shared_task(bind=True, name="maps.process_map_job")
def process_map_job(self, job_id: str, schema_name: str) -> str:
    with schema_context(schema_name):
        job = _start_scene_search(job_id, self.request.id)
        if job.status in MapJob.Status.terminal_values():
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
        if not _update_job_status(
            job_id=job_id,
            status=MapJob.Status.DOWNLOADING,
            progress=20,
            current_step="Obtendo bandas pela Sentinel Hub Process API",
            scene=scene,
        ):
            return MapJob.objects.only("status").get(pk=job_id).status

        try:
            with TemporaryDirectory(prefix="delta-mapas-") as temporary_directory:
                result = process_scene_index(
                    index_type=job.index_type,
                    scene=scene,
                    geometry=job.geometry_snapshot,
                    max_cloud_cover=job.max_cloud_cover,
                    target_directory=temporary_directory,
                    status_callback=lambda stage: _pipeline_status_callback(
                        job_id, stage
                    ),
                )
                if not _update_job_status(
                    job_id=job_id,
                    status=MapJob.Status.RENDERING,
                    progress=70,
                    current_step="Compondo mapa cartográfico PNG/PDF",
                ):
                    return MapJob.objects.only("status").get(pk=job_id).status
                property_name = job.property.name if job.property else "Área avulsa"
                area_hectares = (
                    job.property.area_hectares
                    if job.property
                    else calculate_area_hectares(job.geometry_snapshot)
                )
                rendered = render_index_map(
                    data=result.data,
                    valid_mask=result.valid_mask,
                    raster_metadata=result.metadata["raster"],
                    geometry=job.geometry_snapshot,
                    property_name=property_name,
                    area_hectares=area_hectares,
                    scene=scene,
                    generated_at=timezone.now(),
                    target_directory=temporary_directory,
                )
                if not _update_job_status(
                    job_id=job_id,
                    status=MapJob.Status.UPLOADING,
                    progress=85,
                    current_step="Armazenando produtos finais privados",
                ):
                    return MapJob.objects.only("status").get(pk=job_id).status
                generated_map = persist_generated_map(
                    job=job,
                    scene=scene,
                    rendered=rendered,
                    pipeline_metadata=result.metadata,
                )
        except MapJobCancelled:
            return MapJob.Status.CANCELLED
        except (
            CopernicusAuthenticationUnavailable,
            SatelliteProcessUnavailable,
        ) as exc:
            logger.warning(
                "Transient Sentinel Hub processing failure",
                exc_info=True,
                extra={
                    "job_id": job.id,
                    "user_id": job.created_by_id,
                    "stac_item_id": scene.item_id,
                },
            )
            if self.request.retries < settings.COPERNICUS_PROCESS_MAX_RETRIES:
                raise self.retry(
                    exc=exc,
                    countdown=settings.COPERNICUS_PROCESS_RETRY_DELAY_SECONDS,
                    max_retries=settings.COPERNICUS_PROCESS_MAX_RETRIES,
                )
            return _fail_job(
                job_id=job_id,
                error_code="SATELLITE_PROCESS_UNAVAILABLE",
                error_message=(
                    "O serviço de imagens está temporariamente indisponível. "
                    "Tente novamente mais tarde."
                ),
                current_step="Falha temporária ao obter bandas",
                progress=20,
                scene=scene,
            )
        except PipelineStepFailure as exc:
            logger.exception(
                "Map pipeline step failed: %s",
                type(exc).__name__,
                extra={
                    "job_id": job.id,
                    "user_id": job.created_by_id,
                    "stac_item_id": scene.item_id,
                },
            )
            return _fail_job(
                job_id=job_id,
                error_code=exc.error_code,
                error_message=exc.default_message,
                current_step=exc.current_step,
                progress=exc.progress,
                scene=scene,
            )
        except Exception:
            logger.exception(
                "Unexpected map pipeline failure",
                extra={
                    "job_id": job.id,
                    "user_id": job.created_by_id,
                    "stac_item_id": scene.item_id,
                },
            )
            return _fail_job(
                job_id=job_id,
                error_code="INTERNAL_PROCESSING_ERROR",
                error_message="O processamento falhou por um erro interno.",
                current_step="Falha interna no processamento",
                progress=50,
                scene=scene,
            )

        logger.info(
            "Generated map completed",
            extra={
                "job_id": job.id,
                "user_id": job.created_by_id,
                "stac_item_id": scene.item_id,
                "generated_map_id": generated_map.id,
                "valid_pixel_count": result.metadata["valid_pixel_count"],
            },
        )
        return MapJob.Status.COMPLETED
