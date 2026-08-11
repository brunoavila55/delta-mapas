from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import rasterio
from django.conf import settings
from numpy.typing import NDArray
from rasterio.errors import RasterioError

from ..exceptions import RasterProcessingError
from .copernicus import CopernicusScene
from .processors import get_index_processor
from .sentinel_hub import get_sentinel_hub_process_client


@dataclass(frozen=True, slots=True)
class PipelineProcessingResult:
    data: NDArray[np.float32]
    valid_mask: NDArray[np.bool_]
    metadata: dict[str, object]


def _read_aligned_bands(raster_path: Path) -> tuple[dict[str, Any], dict[str, object]]:
    try:
        with rasterio.open(raster_path) as dataset:
            if dataset.count != 4:
                raise RasterProcessingError(
                    "O raster Sentinel deve conter B04, B08, SCL e dataMask."
                )
            pixel_count = dataset.width * dataset.height
            if pixel_count <= 0 or pixel_count > settings.COPERNICUS_MAX_OUTPUT_PIXELS:
                raise RasterProcessingError(
                    "O raster Sentinel possui dimensões fora dos limites permitidos."
                )
            if dataset.crs is None:
                raise RasterProcessingError("O raster Sentinel não possui CRS.")

            raster_bands = dataset.read(indexes=[1, 2, 3, 4])
            raster_masks = dataset.read_masks(indexes=[1, 2, 3, 4])
            red, nir, scl, data_mask = raster_bands
            red_mask, nir_mask, scl_mask, data_mask_mask = raster_masks
            red_invalid = red_mask == 0
            nir_invalid = nir_mask == 0
            scl_invalid = scl_mask == 0
            outside_aoi = (data_mask_mask == 0) | (data_mask <= 0)

            bands = {
                "B04": np.ma.array(
                    red,
                    mask=red_invalid | outside_aoi,
                ),
                "B08": np.ma.array(
                    nir,
                    mask=nir_invalid | outside_aoi,
                ),
                "SCL": np.ma.array(
                    scl,
                    mask=scl_invalid | outside_aoi,
                ),
            }
            raster_metadata: dict[str, object] = {
                "width": dataset.width,
                "height": dataset.height,
                "crs": dataset.crs.to_string(),
                "resolution": [abs(dataset.res[0]), abs(dataset.res[1])],
                "bounds": list(dataset.bounds),
            }
            return bands, raster_metadata
    except RasterProcessingError:
        raise
    except (RasterioError, OSError, ValueError) as exc:
        raise RasterProcessingError(
            "Não foi possível ler o raster retornado pela Sentinel Hub."
        ) from exc


def process_scene_index(
    *,
    index_type: str,
    scene: CopernicusScene,
    geometry,
    max_cloud_cover,
    target_directory: Path | str,
    process_client=None,
    status_callback: Callable[[str], None] | None = None,
) -> PipelineProcessingResult:
    client = process_client or get_sentinel_hub_process_client()
    target_directory = Path(target_directory)
    downloaded = client.download_bands(
        scene=scene,
        geometry=geometry,
        max_cloud_cover=max_cloud_cover,
        target_directory=target_directory,
    )
    if status_callback:
        status_callback("PREPROCESSING")
    bands, raster_metadata = _read_aligned_bands(downloaded.path)
    if status_callback:
        status_callback("PROCESSING")
    processor = get_index_processor(index_type)
    result = processor.process(bands, nodata_values={"B04": -9999, "B08": -9999})

    valid_values = result.data[result.valid_mask]
    if valid_values.size == 0:
        raise RasterProcessingError(
            "Nenhum pixel válido restou após aplicar as máscaras da cena."
        )

    metadata = {
        **result.metadata,
        "stac_item_id": scene.item_id,
        "scene_date": scene.acquired_at.isoformat(),
        "cloud_cover": str(scene.cloud_cover),
        "download_size_bytes": downloaded.size_bytes,
        "raster": raster_metadata,
        "statistics": {
            "minimum": float(np.min(valid_values)),
            "maximum": float(np.max(valid_values)),
            "mean": float(np.mean(valid_values)),
        },
    }
    return PipelineProcessingResult(
        data=result.data,
        valid_mask=result.valid_mask,
        metadata=metadata,
    )
