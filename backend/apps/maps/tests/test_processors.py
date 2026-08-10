import numpy as np
from django.test import SimpleTestCase

from apps.maps.exceptions import RasterProcessingError
from apps.maps.services.processors import NDVIProcessor, get_index_processor


class NDVIProcessorTests(SimpleTestCase):
    def test_calculates_ndvi_and_masks_invalid_pixels(self):
        bands = {
            "B04": np.array([[1, 0, 1], [np.nan, 1, 2]], dtype=np.float32),
            "B08": np.array([[3, 0, 3], [2, 3, 2]], dtype=np.float32),
            "SCL": np.array([[4, 4, 8], [4, 11, 5]], dtype=np.uint8),
        }

        result = NDVIProcessor().process(bands)

        expected = np.array(
            [[0.5, np.nan, np.nan], [np.nan, np.nan, 0.0]], dtype=np.float32
        )
        np.testing.assert_allclose(result.data, expected, equal_nan=True)
        np.testing.assert_array_equal(
            result.valid_mask,
            np.array([[True, False, False], [False, False, True]], dtype=bool),
        )
        self.assertEqual(result.metadata["valid_pixel_count"], 2)
        self.assertEqual(result.metadata["total_pixel_count"], 6)

    def test_honors_masked_arrays_and_explicit_nodata(self):
        red = np.ma.array([[2, 99], [1, 1]], mask=[[False, False], [True, False]])
        bands = {
            "B04": red,
            "B08": np.array([[6, 99], [3, -9999]], dtype=np.float32),
            "SCL": np.array([[4, 4], [4, 4]], dtype=np.uint8),
        }

        result = NDVIProcessor().process(
            bands,
            nodata_values={"B04": 99, "B08": -9999},
        )

        self.assertAlmostEqual(float(result.data[0, 0]), 0.5)
        self.assertEqual(int(np.count_nonzero(result.valid_mask)), 1)
        self.assertTrue(np.isnan(result.data[0, 1]))
        self.assertTrue(np.isnan(result.data[1, 0]))
        self.assertTrue(np.isnan(result.data[1, 1]))

    def test_cloud_classes_are_configurable(self):
        bands = {
            "B04": np.array([[1]], dtype=np.float32),
            "B08": np.array([[3]], dtype=np.float32),
            "SCL": np.array([[8]], dtype=np.uint8),
        }

        default_result = NDVIProcessor().process(bands)
        custom_result = NDVIProcessor(invalid_scl_classes=frozenset()).process(bands)

        self.assertFalse(default_result.valid_mask[0, 0])
        self.assertTrue(custom_result.valid_mask[0, 0])

    def test_rejects_missing_or_misaligned_bands(self):
        processor = NDVIProcessor()
        with self.assertRaises(RasterProcessingError):
            processor.process({"B04": np.ones((2, 2)), "B08": np.ones((2, 2))})
        with self.assertRaises(RasterProcessingError):
            processor.process(
                {
                    "B04": np.ones((2, 2)),
                    "B08": np.ones((2, 2)),
                    "SCL": np.ones((1, 1)),
                }
            )

    def test_processor_registry_returns_ndvi(self):
        self.assertIsInstance(get_index_processor("NDVI"), NDVIProcessor)
        with self.assertRaises(ValueError):
            get_index_processor("UNSUPPORTED")
