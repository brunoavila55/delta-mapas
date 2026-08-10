import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.exceptions import ValidationError

from apps.properties.services import calculate_area_hectares, normalize_multipolygon


def test_polygon_is_normalized_to_multipolygon():
    polygon = Polygon(((0, 0), (0, 0.01), (0.01, 0.01), (0.01, 0), (0, 0)), srid=4326)

    normalized = normalize_multipolygon(polygon)

    assert isinstance(normalized, MultiPolygon)
    assert calculate_area_hectares(normalized) > 0


def test_empty_geometry_is_rejected():
    with pytest.raises(ValidationError):
        normalize_multipolygon(MultiPolygon(srid=4326))
