from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class IndexProcessingResult:
    data: NDArray[np.float32]
    valid_mask: NDArray[np.bool_]
    metadata: dict[str, object]


class BaseIndexProcessor(ABC):
    required_bands: tuple[str, ...] = ()

    @abstractmethod
    def process(
        self,
        bands: Mapping[str, NDArray],
        *,
        nodata_values: Mapping[str, float | int | None] | None = None,
    ) -> IndexProcessingResult:
        raise NotImplementedError
