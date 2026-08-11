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


class CopernicusConfigurationError(MapJobError):
    pass


class CopernicusAuthenticationError(MapJobError):
    pass


class CopernicusAuthenticationUnavailable(CopernicusAuthenticationError):
    pass


class SatelliteProcessError(MapJobError):
    pass


class SatelliteProcessUnavailable(SatelliteProcessError):
    pass


class SatelliteProcessRejected(SatelliteProcessError):
    pass


class RasterProcessingError(MapJobError):
    pass


class MapRenderingError(MapJobError):
    pass


class StorageUploadError(MapJobError):
    pass


class MapFinalizationError(MapJobError):
    pass
