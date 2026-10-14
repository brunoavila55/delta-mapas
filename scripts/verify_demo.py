"""Independent scientific check. QA only; Python is not part of the application."""
import json
import sys
import re
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from pypdf import PdfReader
from pyproj import Transformer, Geod
from shapely.geometry import shape
from shapely import contains_xy

directory = Path(sys.argv[1])
metadata = json.loads((directory / "analysis.json").read_text())
assert metadata["source"]["kind"] == "synthetic", "Only verify the deterministic demo"
with rasterio.open(directory / "bands.tif") as source:
    red, nir, scl, mask = source.read().astype(np.float64)
    assert source.crs.to_epsg() == 4326
    inside = geometry_mask([metadata["geometry"]], out_shape=red.shape,
                           transform=source.transform, invert=True)
    valid = (inside & (mask == 1) & np.isin(scl, [4, 5, 6])
             & np.isfinite(red) & np.isfinite(nir) & (red >= 0) & (nir >= 0)
             & ((red + nir) > 1e-6))
    reference = np.full(red.shape, -9999.0, dtype=np.float32)
    reference[valid] = ((nir[valid] - red[valid]) / (nir[valid] + red[valid])).astype(np.float32)
    with rasterio.open(directory / "ndvi.tif") as result:
        assert result.crs.to_epsg() == metadata["grid"]["epsg"]
        assert result.crs.to_epsg() != 4326
        assert result.transform.a == 10 and result.transform.e == -10
        assert result.nodata == -9999
        rows, columns = np.indices((result.height, result.width))
        xs = result.transform.c + (columns + 0.5) * result.transform.a
        ys = result.transform.f + (rows + 0.5) * result.transform.e
        lon, lat = Transformer.from_crs(result.crs, 4326, always_xy=True).transform(xs, ys)
        export_inside = contains_xy(shape(metadata["geometry"]), lon, lat)
        source_columns = np.floor((lon-source.transform.c)/source.transform.a).astype(int)
        source_rows = np.floor((lat-source.transform.f)/source.transform.e).astype(int)
        overlaps = (export_inside & (source_columns >= 0) & (source_columns < source.width)
                    & (source_rows >= 0) & (source_rows < source.height))
        expected = np.full(rows.shape, -9999.0, dtype=np.float32)
        expected[overlaps] = reference[source_rows[overlaps], source_columns[overlaps]]
        np.testing.assert_allclose(result.read(1), expected, atol=1e-6, rtol=0)
        assert np.all(result.read(1)[~export_inside] == -9999)
assert metadata["cadastral_crs"] == "EPSG:4674"
canonical_area = abs(Geod(ellps='GRS80').geometry_area_perimeter(shape(metadata["cadastral_geometry"]))[0])/10000
assert abs(canonical_area - metadata["area_ha"]) < 1e-6

stats = metadata["statistics"]
assert stats["pixels_in_area"] == int(inside.sum())
assert stats["valid_pixels"] == int(valid.sum())
assert abs(stats["mean"] - float(reference[valid].astype(np.float64).mean())) < 1e-7
assert abs(stats["minimum"] - float(reference[valid].min())) < 1e-7
assert abs(stats["maximum"] - float(reference[valid].max())) < 1e-7
assert abs(stats["valid_percent"] - valid.sum() / inside.sum() * 100) < 1e-7
reader = PdfReader(directory / "report.pdf", strict=True)
assert len(reader.pages) == 2
resources = reader.pages[1]["/Resources"]
assert "/F1" in resources["/Font"]
assert "/Map" in resources["/XObject"]
assert "SINTÉTICOS" in reader.pages[0].extract_text()
map_reader = PdfReader(directory / "map.pdf", strict=True)
assert len(map_reader.pages) == 1
assert "Escala 1:" in map_reader.pages[0].extract_text()
assert "EPSG:" in map_reader.pages[0].extract_text()
assert sum(metadata["distribution"]["valid_pixel_counts"]) == stats["valid_pixels"]
np.testing.assert_array_equal(np.histogram(reference[valid], bins=metadata["distribution"]["bounds"])[0], metadata["distribution"]["valid_pixel_counts"])
operations = map_reader.pages[0].get_contents().operations
placement = next(operations[i-1][0] for i, (args, op) in enumerate(operations) if op == b'Do' and str(args[0]) == '/Map')
printed_scale = float(re.search(r'Escala 1:(\d+)', map_reader.pages[0].extract_text()).group(1))
expected_scale = metadata["grid"]["width"] * metadata["grid"]["dx"] / float(placement[0]) * 72 / 0.0254
assert abs(printed_scale - expected_scale) <= 1.0
for document in [reader, map_reader]:
    for page in document.pages:
        for font in page["/Resources"]["/Font"].values():
            assert "/FontFile2" in font.get_object()["/FontDescriptor"]

print(json.dumps({"independent_check": "passed", "reference": "NumPy + Rasterio/GDAL",
                  "pixels_in_area": stats["pixels_in_area"], "valid_pixels": stats["valid_pixels"],
                  "mean_ndvi": stats["mean"], "pdf_pages": len(reader.pages)}, indent=2))
