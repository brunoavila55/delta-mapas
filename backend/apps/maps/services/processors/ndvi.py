from __future__ import annotations

from typing import Mapping

import numpy as np
from numpy.typing import NDArray

from ...exceptions import RasterProcessingError
from .base import BaseIndexProcessor, IndexProcessingResult

DEFAULT_INVALID_SCL_CLASSES = frozenset({0, 1, 3, 8, 9, 10, 11})


def _float_data_and_mask(values: NDArray) -> tuple[NDArray[np.float32], NDArray]:
    masked = np.ma.asarray(values, dtype=np.float32)
    data = np.asarray(masked.filled(np.nan))
    return data, np.ma.getmaskarray(masked)


class NDVIProcessor(BaseIndexProcessor):
    required_bands = ("B04", "B08", "SCL")

    def __init__(self, *, invalid_scl_classes: frozenset[int] | None = None) -> None:
        self.invalid_scl_classes = (
            invalid_scl_classes
            if invalid_scl_classes is not None
            else DEFAULT_INVALID_SCL_CLASSES
        )

    def process(
        self,
        bands: Mapping[str, NDArray],
        *,
        nodata_values: Mapping[str, float | int | None] | None = None,
    ) -> IndexProcessingResult:
        missing = [name for name in self.required_bands if name not in bands]
        if missing:
            raise RasterProcessingError(
                f"Bandas obrigatórias ausentes: {', '.join(missing)}."
            )

        red, red_mask = _float_data_and_mask(bands["B04"])
        nir, nir_mask = _float_data_and_mask(bands["B08"])
        scl_masked = np.ma.asarray(bands["SCL"], dtype=np.int16)
        scl = np.asarray(scl_masked.filled(-1))
        scl_mask = np.ma.getmaskarray(scl_masked)

        if red.ndim != 2 or nir.shape != red.shape or scl.shape != red.shape:
            raise RasterProcessingError(
                "B04, B08 e SCL devem ser matrizes 2D com dimensões idênticas."
            )

        valid = ~(red_mask | nir_mask | scl_mask)
        valid &= np.isfinite(red) & np.isfinite(nir)
        valid &= ~np.isin(scl, tuple(self.invalid_scl_classes))

        nodata_values = nodata_values or {}
        red_nodata = nodata_values.get("B04")
        nir_nodata = nodata_values.get("B08")
        scl_nodata = nodata_values.get("SCL")
        if red_nodata is not None:
            valid &= red != red_nodata
        if nir_nodata is not None:
            valid &= nir != nir_nodata
        if scl_nodata is not None:
            valid &= scl != scl_nodata

        denominator = nir + red
        valid &= np.isfinite(denominator) & (denominator != 0)

        ndvi = np.full(red.shape, np.nan, dtype=np.float32)
        np.divide(nir - red, denominator, out=ndvi, where=valid)

        return IndexProcessingResult(
            data=ndvi,
            valid_mask=valid,
            metadata={
                "index": "NDVI",
                "formula": "(B08 - B04) / (B08 + B04)",
                "invalid_scl_classes": sorted(self.invalid_scl_classes),
                "valid_pixel_count": int(np.count_nonzero(valid)),
                "total_pixel_count": int(valid.size),
            },
        )
