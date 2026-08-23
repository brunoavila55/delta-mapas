class MapJobError(Exception):
    pass


class MapJobIdempotencyConflict(MapJobError):
    pass


class MapJobEnqueueError(MapJobError):
    pass


class MapJobTransitionConflict(MapJobError):
    pass


class MapJobCancelled(MapJobError):
    pass


class NoSatelliteSceneFound(MapJobError):
    pass


class SatelliteCatalogError(MapJobError):
    pass


class PipelineStepFailure(MapJobError):
    """Base for pipeline errors that fail a MapJob immediately (no retry).

    Subclasses carry the metadata `process_map_job` needs to record the
    failure, so the task can handle all of them with a single `except`
    instead of one copy-pasted block per error type.
    """

    error_code: str
    default_message: str
    current_step: str
    progress: int


class CopernicusConfigurationError(PipelineStepFailure):
    error_code = "COPERNICUS_AUTH_NOT_CONFIGURED"
    default_message = "A integração de imagens ainda não foi configurada."
    current_step = "Integração Copernicus não configurada"
    progress = 20


class CopernicusAuthenticationError(PipelineStepFailure):
    error_code = "COPERNICUS_AUTH_FAILED"
    default_message = "Não foi possível autenticar no serviço de imagens."
    current_step = "Falha de autenticação Copernicus"
    progress = 20


class CopernicusAuthenticationUnavailable(CopernicusAuthenticationError):
    pass


class SatelliteProcessError(MapJobError):
    pass


class SatelliteProcessUnavailable(SatelliteProcessError):
    pass


class SatelliteProcessRejected(SatelliteProcessError, PipelineStepFailure):
    error_code = "SATELLITE_PROCESS_REJECTED"
    default_message = "O serviço de imagens recusou a solicitação raster."
    current_step = "Solicitação raster recusada"
    progress = 20


class RasterProcessingError(PipelineStepFailure):
    error_code = "RASTER_PROCESSING_ERROR"
    default_message = "Não foi possível processar as bandas da cena selecionada."
    current_step = "Falha no processamento raster"
    progress = 50


class MapRenderingError(PipelineStepFailure):
    error_code = "MAP_RENDERING_ERROR"
    default_message = "Não foi possível renderizar o mapa cartográfico."
    current_step = "Falha na renderização do mapa"
    progress = 70


class StorageUploadError(PipelineStepFailure):
    error_code = "STORAGE_UPLOAD_ERROR"
    default_message = "Não foi possível armazenar os arquivos finais do mapa."
    current_step = "Falha ao armazenar produtos finais"
    progress = 85


class MapFinalizationError(PipelineStepFailure):
    error_code = "MAP_FINALIZATION_ERROR"
    default_message = "Não foi possível concluir o mapa e a cobrança."
    current_step = "Falha ao finalizar mapa"
    progress = 85
