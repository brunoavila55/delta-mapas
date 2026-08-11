from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.test import SimpleTestCase, override_settings
from PIL import Image

from apps.maps.exceptions import MapRenderingError
from apps.maps.services.copernicus import CopernicusScene
from apps.maps.services.rendering import render_index_map


@override_settings(
    MAP_RENDER_MAX_DIMENSION_PIXELS=100,
    MAP_RENDER_PNG_DPI=72,
    MAP_RENDER_PDF_DPI=72,
)
class MapRenderingTests(SimpleTestCase):
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
        projected = self.geometry.clone()
        projected.transform(32722)
        self.bounds = list(projected.extent)
        self.scene = CopernicusScene(
            item_id="sentinel-render-scene",
            acquired_at=datetime(2026, 7, 20, 13, tzinfo=timezone.utc),
            cloud_cover=Decimal("2.5"),
            assets={"B04": "red", "B08": "nir", "SCL": "scl"},
            collection="sentinel-2-l2a",
            platform="sentinel-2c",
        )

    def test_generates_presentable_png_and_pdf(self):
        y_values, x_values = np.mgrid[-1:1:40j, -1:1:60j]
        data = np.asarray(0.6 - (x_values**2 + y_values**2) / 2, dtype=np.float32)
        valid_mask = (x_values**2 + y_values**2) <= 1

        with TemporaryDirectory() as temporary_directory:
            rendered = render_index_map(
                data=data,
                valid_mask=valid_mask,
                raster_metadata={"crs": "EPSG:32722", "bounds": self.bounds},
                geometry=self.geometry,
                property_name="Fazenda Delta",
                area_hectares=Decimal("12.34"),
                scene=self.scene,
                generated_at=datetime(2026, 8, 10, 15, tzinfo=timezone.utc),
                target_directory=temporary_directory,
            )

            self.assertTrue(rendered.png_path.read_bytes().startswith(b"\x89PNG"))
            self.assertTrue(rendered.pdf_path.read_bytes().startswith(b"%PDF"))
            self.assertGreater(rendered.png_path.stat().st_size, 10_000)
            self.assertGreater(rendered.pdf_path.stat().st_size, 5_000)
            with Image.open(rendered.png_path) as image:
                self.assertGreater(image.width, image.height)
                self.assertEqual(image.format, "PNG")
            self.assertEqual(rendered.metadata["template"], "ndvi-a4-landscape-v1")
            self.assertEqual(rendered.metadata["downsample_step"], 1)

    def test_rejects_invalid_or_empty_render_input(self):
        cases = (
            (np.ones((2, 2), dtype=np.float32), np.ones((1, 2), dtype=bool)),
            (np.ones((2, 2), dtype=np.float32), np.zeros((2, 2), dtype=bool)),
        )
        for data, valid_mask in cases:
            with self.subTest(mask_shape=valid_mask.shape):
                with TemporaryDirectory() as temporary_directory:
                    with self.assertRaises(MapRenderingError):
                        render_index_map(
                            data=data,
                            valid_mask=valid_mask,
                            raster_metadata={
                                "crs": "EPSG:32722",
                                "bounds": self.bounds,
                            },
                            geometry=self.geometry,
                            property_name="Área",
                            area_hectares=1,
                            scene=self.scene,
                            generated_at=datetime.now(timezone.utc),
                            target_directory=Path(temporary_directory),
                        )
