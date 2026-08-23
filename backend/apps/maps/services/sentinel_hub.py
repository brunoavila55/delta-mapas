from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from django.conf import settings

from ..exceptions import (
    CopernicusAuthenticationError,
    RasterProcessingError,
    SatelliteProcessRejected,
    SatelliteProcessUnavailable,
)
from .copernicus import CopernicusScene
from .oauth import OAuthTokenProvider

SENTINEL_BANDS_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{
      bands: ["B04", "B08", "SCL", "dataMask"],
      units: ["REFLECTANCE", "REFLECTANCE", "DN", "DN"]
    }],
    output: {
      id: "default",
      bands: 4,
      sampleType: "FLOAT32",
      nodataValue: -9999
    }
  };
}

function evaluatePixel(sample) {
  if (sample.dataMask === 0) {
    return [-9999, -9999, 0, 0];
  }
  return [sample.B04, sample.B08, sample.SCL, sample.dataMask];
}
"""


@dataclass(frozen=True, slots=True)
class ProcessGrid:
    epsg: int
    width: int
    height: int
    pixel_count: int


@dataclass(frozen=True, slots=True)
class DownloadedRaster:
    path: Path
    grid: ProcessGrid
    size_bytes: int


def _utm_epsg(geometry) -> int:
    source = geometry.clone()
    if source.srid != 4326:
        source.transform(4326)
    centroid = source.centroid
    longitude = centroid.x
    latitude = centroid.y
    if not (-80 <= latitude <= 84):
        raise RasterProcessingError(
            "A área solicitada está fora da cobertura das projeções UTM suportadas."
        )
    zone = min(60, max(1, math.floor((longitude + 180) / 6) + 1))
    return (32600 if latitude >= 0 else 32700) + zone


def build_process_request(
    *,
    scene: CopernicusScene,
    geometry,
    max_cloud_cover,
) -> tuple[dict[str, object], ProcessGrid]:
    epsg = _utm_epsg(geometry)
    projected = geometry.clone()
    if projected.srid != epsg:
        projected.transform(epsg)

    xmin, ymin, xmax, ymax = projected.extent
    resolution = settings.COPERNICUS_OUTPUT_RESOLUTION_METERS
    if resolution <= 0:
        raise RasterProcessingError("A resolução de saída deve ser maior que zero.")
    width = max(1, math.ceil((xmax - xmin) / resolution))
    height = max(1, math.ceil((ymax - ymin) / resolution))
    pixel_count = width * height
    if pixel_count > settings.COPERNICUS_MAX_OUTPUT_PIXELS:
        raise RasterProcessingError(
            "A área solicitada excede o limite de pixels do processamento."
        )

    tolerance = timedelta(seconds=settings.COPERNICUS_SCENE_TIME_TOLERANCE_SECONDS)
    acquired_at = scene.acquired_at
    if acquired_at.tzinfo is None:
        acquired_at = acquired_at.replace(tzinfo=timezone.utc)
    acquired_at = acquired_at.astimezone(timezone.utc)

    def iso_utc(value) -> str:
        return value.isoformat().replace("+00:00", "Z")

    grid = ProcessGrid(
        epsg=epsg,
        width=width,
        height=height,
        pixel_count=pixel_count,
    )
    payload: dict[str, object] = {
        "input": {
            "bounds": {
                "geometry": json.loads(projected.geojson),
                "properties": {"crs": f"http://www.opengis.net/def/crs/EPSG/0/{epsg}"},
            },
            "data": [
                {
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "timeRange": {
                            "from": iso_utc(acquired_at - tolerance),
                            "to": iso_utc(acquired_at + tolerance),
                        },
                        "mosaickingOrder": "leastCC",
                        "maxCloudCoverage": float(max_cloud_cover),
                    },
                    "processing": {
                        "upsampling": "NEAREST",
                        "downsampling": "BILINEAR",
                    },
                }
            ],
        },
        "output": {
            "resx": resolution,
            "resy": resolution,
            "responses": [
                {
                    "identifier": "default",
                    "format": {"type": "image/tiff"},
                }
            ],
        },
        "evalscript": SENTINEL_BANDS_EVALSCRIPT,
    }
    return payload, grid


class SentinelHubProcessClient:
    def __init__(
        self,
        *,
        session: Any | None = None,
        token_provider: OAuthTokenProvider | None = None,
    ) -> None:
        self._session = session or requests.Session()
        self._token_provider = token_provider or OAuthTokenProvider(
            session=self._session
        )

    def _post(self, payload: dict[str, object], *, refresh_on_unauthorized: bool):
        token = self._token_provider.get_access_token()
        try:
            response = self._session.post(
                settings.COPERNICUS_PROCESS_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "image/tiff",
                    "Content-Type": "application/json",
                },
                timeout=settings.COPERNICUS_PROCESS_TIMEOUT_SECONDS,
                stream=True,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise SatelliteProcessUnavailable(
                "A Sentinel Hub Process API está indisponível."
            ) from exc

        if response.status_code in {401, 403} and refresh_on_unauthorized:
            response.close()
            self._token_provider.invalidate()
            return self._post(payload, refresh_on_unauthorized=False)
        if response.status_code in {401, 403}:
            response.close()
            raise CopernicusAuthenticationError(
                "A Sentinel Hub Process API recusou a autenticação."
            )
        if response.status_code == 429 or response.status_code >= 500:
            response.close()
            raise SatelliteProcessUnavailable(
                "A Sentinel Hub Process API está temporariamente indisponível."
            )
        if response.status_code >= 300:
            response.close()
            raise SatelliteProcessRejected(
                "A Sentinel Hub Process API recusou a solicitação raster."
            )
        return response

    def download_bands(
        self,
        *,
        scene: CopernicusScene,
        geometry,
        max_cloud_cover,
        target_directory: Path,
    ) -> DownloadedRaster:
        payload, grid = build_process_request(
            scene=scene,
            geometry=geometry,
            max_cloud_cover=max_cloud_cover,
        )
        target_directory = target_directory.resolve()
        target_directory.mkdir(parents=True, exist_ok=True)
        final_path = target_directory / "sentinel-input.tif"
        partial_path = target_directory / "sentinel-input.tif.part"
        response = self._post(payload, refresh_on_unauthorized=True)
        maximum_bytes = settings.COPERNICUS_MAX_DOWNLOAD_BYTES

        try:
            content_type = response.headers.get("Content-Type", "").lower()
            if content_type and not any(
                allowed in content_type
                for allowed in (
                    "image/tiff",
                    "image/geotiff",
                    "application/octet-stream",
                )
            ):
                raise SatelliteProcessRejected(
                    "A Sentinel Hub retornou um formato raster inesperado."
                )
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    declared_bytes = int(content_length)
                except ValueError as exc:
                    raise SatelliteProcessRejected(
                        "A Sentinel Hub retornou um tamanho de raster inválido."
                    ) from exc
                if declared_bytes < 0 or declared_bytes > maximum_bytes:
                    raise SatelliteProcessRejected(
                        "A resposta raster excede o limite de download."
                    )

            downloaded = 0
            with partial_path.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > maximum_bytes:
                        raise SatelliteProcessRejected(
                            "A resposta raster excede o limite de download."
                        )
                    output.write(chunk)
            if downloaded == 0:
                raise SatelliteProcessRejected(
                    "A Sentinel Hub retornou um raster vazio."
                )
            partial_path.replace(final_path)
            return DownloadedRaster(path=final_path, grid=grid, size_bytes=downloaded)
        except requests.RequestException as exc:
            raise SatelliteProcessUnavailable(
                "O download do raster Sentinel foi interrompido."
            ) from exc
        finally:
            response.close()
            partial_path.unlink(missing_ok=True)


@lru_cache(maxsize=1)
def get_sentinel_hub_process_client() -> SentinelHubProcessClient:
    return SentinelHubProcessClient()
