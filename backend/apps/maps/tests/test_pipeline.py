from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import rasterio
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import SimpleTestCase, override_settings
from rasterio.transform import from_origin

from apps.maps.exceptions import RasterProcessingError
from apps.maps.services.copernicus import CopernicusScene
from apps.maps.services.pipeline import process_scene_index
from apps.maps.services.sentinel_hub import DownloadedRaster, ProcessGrid


class RasterFixtureClient:
    def __init__(self, bands: np.ndarray):
        self.bands = bands

    def download_bands(
        self,
        *,
        scene,
        geometry,
        max_cloud_cover,
        target_directory,
    ):
        path = Path(target_directory) / "sentinel-input.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=self.bands.shape[2],
            height=self.bands.shape[1],
            count=self.bands.shape[0],
            dtype="float32",
            crs="EPSG:32722",
            transform=from_origin(500000, 8300000, 10, 10),
            nodata=-9999,
        ) as dataset:
            dataset.write(self.bands.astype(np.float32))
        return DownloadedRaster(
            path=path,
            grid=ProcessGrid(
                epsg=32722,
                width=self.bands.shape[2],
                height=self.bands.shape[1],
                pixel_count=self.bands.shape[1] * self.bands.shape[2],
            ),
            size_bytes=path.stat().st_size,
        )


@override_settings(COPERNICUS_MAX_OUTPUT_PIXELS=1000)
class PipelineProcessingTests(SimpleTestCase):
    def setUp(self):
        polygon = Polygon(
            (
                (-48.001, -15.001),
                (-48.001, -15.000),
                (-48.000, -15.000),
                (-48.000, -15.001),
                (-48.001, -15.001),
            ),
            srid=4326,
        )
        self.geometry = MultiPolygon(polygon, srid=4326)
        self.scene = CopernicusScene(
            item_id="sentinel-scene-pipeline",
            acquired_at=datetime(2026, 7, 20, 13, tzinfo=timezone.utc),
            cloud_cover=Decimal("2.5"),
            assets={"B04": "red", "B08": "nir", "SCL": "scl"},
            collection="sentinel-2-l2a",
            platform="sentinel-2c",
        )

    def test_reads_aligned_raster_masks_clouds_and_calculates_ndvi(self):
        bands = np.array(
            [
                [[0.2, 0.2, 0.0], [0.1, 0.2, 0.2]],
                [[0.6, 0.6, 0.0], [0.3, 0.6, 0.6]],
                [[4, 8, 4], [5, 4, 4]],
                [[1, 1, 1], [1, 0, 1]],
            ],
            dtype=np.float32,
        )
        stages = []

        with TemporaryDirectory() as temporary_directory:
            result = process_scene_index(
                index_type="NDVI",
                scene=self.scene,
                geometry=self.geometry,
                max_cloud_cover=20,
                target_directory=temporary_directory,
                process_client=RasterFixtureClient(bands),
                status_callback=stages.append,
            )

        self.assertEqual(stages, ["PREPROCESSING", "PROCESSING"])
        self.assertEqual(result.metadata["valid_pixel_count"], 3)
        self.assertEqual(result.metadata["total_pixel_count"], 6)
        self.assertAlmostEqual(
            result.metadata["statistics"]["minimum"], 0.5, delta=1e-6
        )
        self.assertAlmostEqual(
            result.metadata["statistics"]["maximum"], 0.5, delta=1e-6
        )
        self.assertEqual(result.metadata["raster"]["crs"], "EPSG:32722")
        self.assertEqual(result.metadata["stac_item_id"], "sentinel-scene-pipeline")

    def test_rejects_raster_without_four_expected_bands(self):
        bands = np.ones((3, 2, 2), dtype=np.float32)

        with TemporaryDirectory() as temporary_directory:
            with self.assertRaises(RasterProcessingError):
                process_scene_index(
                    index_type="NDVI",
                    scene=self.scene,
                    geometry=self.geometry,
                    max_cloud_cover=20,
                    target_directory=temporary_directory,
                    process_client=RasterFixtureClient(bands),
                )

    def test_rejects_scene_without_valid_pixels(self):
        bands = np.array(
            [
                [[0.2, 0.2]],
                [[0.6, 0.6]],
                [[8, 9]],
                [[1, 1]],
            ],
            dtype=np.float32,
        )

        with TemporaryDirectory() as temporary_directory:
            with self.assertRaises(RasterProcessingError):
                process_scene_index(
                    index_type="NDVI",
                    scene=self.scene,
                    geometry=self.geometry,
                    max_cloud_cover=20,
                    target_directory=temporary_directory,
                    process_client=RasterFixtureClient(bands),
                )
