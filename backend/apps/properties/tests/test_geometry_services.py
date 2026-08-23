import pytest
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.exceptions import ValidationError

from apps.properties.services import (
    apply_geometry_operation,
    calculate_area_hectares,
    normalize_multipolygon,
    parse_and_validate_geometry,
)


def test_polygon_is_normalized_to_multipolygon():
    polygon = Polygon(((0, 0), (0, 0.01), (0.01, 0.01), (0.01, 0), (0, 0)), srid=4326)

    normalized = normalize_multipolygon(polygon)

    assert isinstance(normalized, MultiPolygon)
    assert calculate_area_hectares(normalized) > 0


def test_empty_geometry_is_rejected():
    with pytest.raises(ValidationError):
        normalize_multipolygon(MultiPolygon(srid=4326))


def test_geojson_string_is_parsed_and_validated_by_domain_service():
    geometry = parse_and_validate_geometry(
        '{"type":"Polygon","coordinates":[[[0,0],[0,0.01],'
        '[0.01,0.01],[0.01,0],[0,0]]]}'
    )

    assert isinstance(geometry, MultiPolygon)
    assert geometry.srid == 4326


def test_domain_service_rejects_non_geojson_input():
    with pytest.raises(ValidationError, match="GeoJSON"):
        parse_and_validate_geometry("POLYGON ((0 0, 0 1, 1 1, 0 0))")


def test_union_connects_components_with_a_drawn_bridge():
    first = Polygon(((0, 0), (0, 2), (2, 2), (2, 0), (0, 0)), srid=4326)
    second = Polygon(((4, 0), (4, 2), (6, 2), (6, 0), (4, 0)), srid=4326)
    bridge = Polygon(
        ((1.5, 0.5), (1.5, 1.5), (4.5, 1.5), (4.5, 0.5), (1.5, 0.5)),
        srid=4326,
    )

    result = apply_geometry_operation(
        geometry=MultiPolygon(first, second, srid=4326),
        operand=bridge,
        operation="union",
    )

    assert result.component_count == 1
    assert result.changed_area_hectares > 0


def test_cut_with_a_drawn_strip_splits_a_component():
    base = Polygon(((0, 0), (0, 4), (6, 4), (6, 0), (0, 0)), srid=4326)
    strip = Polygon(
        ((2.5, -1), (2.5, 5), (3.5, 5), (3.5, -1), (2.5, -1)),
        srid=4326,
    )

    result = apply_geometry_operation(
        geometry=base,
        operand=strip,
        operation="cut",
    )

    assert result.component_count == 2
    assert result.changed_area_hectares > 0
