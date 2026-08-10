from .base import BaseIndexProcessor, IndexProcessingResult
from .ndvi import NDVIProcessor

PROCESSOR_REGISTRY: dict[str, type[BaseIndexProcessor]] = {
    "NDVI": NDVIProcessor,
}


def get_index_processor(index_type: str) -> BaseIndexProcessor:
    try:
        processor_class = PROCESSOR_REGISTRY[index_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported index type: {index_type}") from exc
    return processor_class()


__all__ = (
    "BaseIndexProcessor",
    "IndexProcessingResult",
    "NDVIProcessor",
    "get_index_processor",
)
