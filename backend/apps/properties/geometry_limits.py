from __future__ import annotations

import math

from django.conf import settings

from .exceptions import InvalidGeometry, InvalidShapefile


def validate_geojson_complexity(value: object) -> None:
    if not isinstance(value, dict) or value.get("type") not in {
        "Polygon",
        "MultiPolygon",
    }:
        raise InvalidGeometry("A geometria deve conter ao menos um Polygon válido.")
    coordinates = value.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise InvalidGeometry("A geometria GeoJSON não possui coordenadas válidas.")

    coordinate_count = 0
    component_count = 0
    stack: list[tuple[object, int]] = [(coordinates, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > settings.GEOMETRY_MAX_NESTING_DEPTH:
            raise InvalidGeometry("A geometria excede o limite de profundidade.")
        if not isinstance(node, list) or not node:
            raise InvalidGeometry("A geometria GeoJSON possui uma estrutura inválida.")
        if len(node) >= 2 and all(isinstance(item, (int, float)) for item in node[:2]):
            if not all(math.isfinite(float(item)) for item in node[:2]):
                raise InvalidGeometry("A geometria possui coordenadas não finitas.")
            coordinate_count += 1
            if coordinate_count > settings.GEOMETRY_MAX_COORDINATES:
                raise InvalidGeometry("A geometria excede o limite de coordenadas.")
            continue
        component_count += 1
        if component_count > settings.GEOMETRY_MAX_COMPONENTS:
            raise InvalidGeometry("A geometria excede o limite de componentes.")
        stack.extend((child, depth + 1) for child in node)


def validate_shapely_complexity(geometry) -> None:
    from shapely import get_num_coordinates

    if int(get_num_coordinates(geometry)) > settings.GEOMETRY_MAX_COORDINATES:
        raise InvalidShapefile("A geometria excede o limite de coordenadas.")

    component_count = 0
    stack = [geometry]
    while stack:
        current = stack.pop()
        children = getattr(current, "geoms", None)
        if children is not None:
            stack.extend(children)
        else:
            component_count += 1
        if component_count + len(stack) > settings.GEOMETRY_MAX_COMPONENTS:
            raise InvalidShapefile("A geometria excede o limite de componentes.")
