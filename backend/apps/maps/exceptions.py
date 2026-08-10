class MapJobError(Exception):
    pass


class MapJobIdempotencyConflict(MapJobError):
    pass


class MapJobEnqueueError(MapJobError):
    pass


class NoSatelliteSceneFound(MapJobError):
    pass


class SatelliteCatalogError(MapJobError):
    pass


class RasterProcessingError(MapJobError):
    pass
