from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.properties.exceptions import InvalidGeometry, InvalidShapefile
from apps.properties.importers import _read_geometry
from apps.properties.services import parse_and_validate_geometry


class GeometryComplexityTests(SimpleTestCase):
    @override_settings(GEOMETRY_MAX_COORDINATES=4)
    def test_rejects_geojson_before_geos_parses_excessive_coordinates(self):
        value = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
        }

        with self.assertRaisesMessage(
            InvalidGeometry, "limite de coordenadas"
        ):
            parse_and_validate_geometry(value)

    def test_rejects_wkt_so_complexity_is_always_checked_before_geos(self):
        with self.assertRaisesMessage(InvalidGeometry, "GeoJSON"):
            parse_and_validate_geometry("POLYGON ((0 0, 0 1, 1 1, 0 0))")

    @override_settings(SHAPEFILE_MAX_FEATURES=2)
    @patch("apps.properties.importers.gpd.read_file")
    def test_shapefile_reader_only_loads_one_feature_over_the_limit(self, read_file):
        read_file.return_value = SimpleNamespace(crs="EPSG:4326", index=range(3))

        with self.assertRaisesMessage(InvalidShapefile, "limite de feições"):
            _read_geometry(SimpleNamespace())

        self.assertEqual(read_file.call_args.kwargs["rows"], slice(0, 3))
