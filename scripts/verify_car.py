"""Independent QA for a geographic CAR import; never prints DBF identifiers."""
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
import json
import sys
import unicodedata

import shapefile
from pyproj import CRS, Geod, Transformer
from shapely.geometry import shape
from shapely import transform
from shapely.ops import unary_union

def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text).lower()
                   if c.isascii() and c.isalnum())

with ZipFile(sys.argv[1]) as outer:
    member = next(name for name in outer.namelist() if normalized(Path(name).stem) == 'areadoimovel')
    with ZipFile(BytesIO(outer.read(member))) as layer:
        component = lambda ext: layer.read(next(n for n in layer.namelist() if n.lower().endswith(ext)))
        reader = shapefile.Reader(shp=BytesIO(component('.shp')), shx=BytesIO(component('.shx')),
                                  dbf=BytesIO(component('.dbf')), encoding='utf-8')
        fields = [f[0] for f in reader.fields[1:]]
        theme_index = next(i for i, name in enumerate(fields) if normalized(name) == 'tema')
        polygons = [shape(record.shape.__geo_interface__) for record in reader.iterShapeRecords()
                    if normalized(record.record[theme_index]) in ['areadoimovel', 'areatotaldoimovel', 'areaimovel']]
        source = CRS.from_wkt(component('.prj').decode())
        converter = Transformer.from_crs(source, 4326, always_xy=True)
        reference = transform(unary_union(polygons), converter.transform, interleaved=False)

imported = shape(json.loads(Path(sys.argv[2]).read_text()))
assert imported.is_valid and reference.is_valid
assert reference.hausdorff_distance(imported) < 1e-8
geod = Geod(ellps='WGS84')
ref_area = abs(geod.geometry_area_perimeter(reference)[0]) / 10000
rust_area = abs(geod.geometry_area_perimeter(imported)[0]) / 10000
assert abs(ref_area - rust_area) < 0.0001
print(json.dumps({'check': 'passed', 'reference': 'PyShp + PROJ/pyproj + Shapely',
                  'source_crs': source.name, 'area_ha': rust_area,
                  'selected_features': len(polygons)}, indent=2))
