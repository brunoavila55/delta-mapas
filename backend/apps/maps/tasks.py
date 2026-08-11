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
    CopernicusAuthenticationError,
    CopernicusAuthenticationUnavailable,
    CopernicusConfigurationError,
    MapFinalizationError,
    MapJobCancelled,
    MapRenderingError,
    NoSatelliteSceneFound,
    RasterProcessingError,
    SatelliteCatalogError,
    SatelliteProcessRejected,
    SatelliteProcessUnavailable,
    StorageUploadError,
)
from .models import MapJob
from .services.copernicus import CopernicusScene, CopernicusSceneService
from .services.pipeline import process_scene_index
from .services.products import persist_generated_map
from .services.rendering import render_index_map

logger = logging.getLogger(__name__)


@shared_task(name="maps.healthcheck")
def healthcheck() -> str:
    return "ok"


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
        except CopernicusConfigurationError:
            logger.error(
                "Copernicus OAuth credentials are not configured",
                extra={"job_id": job.id, "user_id": job.created_by_id},
            )
            return _fail_job(
                job_id=job_id,
                error_code="COPERNICUS_AUTH_NOT_CONFIGURED",
                error_message="A integração de imagens ainda não foi configurada.",
                current_step="Integração Copernicus não configurada",
                progress=20,
                scene=scene,
            )
        except CopernicusAuthenticationError:
            logger.error(
                "Copernicus OAuth authentication was rejected",
                extra={"job_id": job.id, "user_id": job.created_by_id},
            )
            return _fail_job(
                job_id=job_id,
                error_code="COPERNICUS_AUTH_FAILED",
                error_message="Não foi possível autenticar no serviço de imagens.",
                current_step="Falha de autenticação Copernicus",
                progress=20,
                scene=scene,
            )
        except SatelliteProcessRejected:
            logger.exception(
                "Sentinel Hub rejected the raster request",
                extra={
                    "job_id": job.id,
                    "user_id": job.created_by_id,
                    "stac_item_id": scene.item_id,
                },
            )
            return _fail_job(
                job_id=job_id,
                error_code="SATELLITE_PROCESS_REJECTED",
                error_message="O serviço de imagens recusou a solicitação raster.",
                current_step="Solicitação raster recusada",
                progress=20,
                scene=scene,
            )
        except RasterProcessingError:
            logger.exception(
                "Raster processing failed",
                extra={
                    "job_id": job.id,
                    "user_id": job.created_by_id,
                    "stac_item_id": scene.item_id,
                },
            )
            return _fail_job(
                job_id=job_id,
                error_code="RASTER_PROCESSING_ERROR",
                error_message="Não foi possível processar as bandas da cena selecionada.",
                current_step="Falha no processamento raster",
                progress=50,
                scene=scene,
            )
        except MapRenderingError:
            logger.exception(
                "Map rendering failed",
                extra={
                    "job_id": job.id,
                    "user_id": job.created_by_id,
                    "stac_item_id": scene.item_id,
                },
            )
            return _fail_job(
                job_id=job_id,
                error_code="MAP_RENDERING_ERROR",
                error_message="Não foi possível renderizar o mapa cartográfico.",
                current_step="Falha na renderização do mapa",
                progress=70,
                scene=scene,
            )
        except StorageUploadError:
            logger.exception(
                "Generated map upload failed",
                extra={
                    "job_id": job.id,
                    "user_id": job.created_by_id,
                    "stac_item_id": scene.item_id,
                },
            )
            return _fail_job(
                job_id=job_id,
                error_code="STORAGE_UPLOAD_ERROR",
                error_message="Não foi possível armazenar os arquivos finais do mapa.",
                current_step="Falha ao armazenar produtos finais",
                progress=85,
                scene=scene,
            )
        except MapFinalizationError:
            logger.exception(
                "Generated map finalization failed",
                extra={
                    "job_id": job.id,
                    "user_id": job.created_by_id,
                    "stac_item_id": scene.item_id,
                },
            )
            return _fail_job(
                job_id=job_id,
                error_code="MAP_FINALIZATION_ERROR",
                error_message="Não foi possível concluir o mapa e a cobrança.",
                current_step="Falha ao finalizar mapa",
                progress=85,
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
