import logging

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon

from .exceptions import InvalidGeometry

logger = logging.getLogger(__name__)


def _polygon_parts(geometry: GEOSGeometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon) or geometry.geom_type == "GeometryCollection":
        parts: list[Polygon] = []
        for child in geometry:
            parts.extend(_polygon_parts(child))
        return parts
    return []


def normalize_multipolygon(geometry: GEOSGeometry) -> MultiPolygon:
    if geometry is None:
        raise InvalidGeometry("A geometria é obrigatória.")
    if geometry.empty:
        raise InvalidGeometry("A geometria não pode ser vazia.")
    if geometry.srid is None:
        geometry.srid = 4326
    if geometry.srid != 4326:
        geometry = geometry.clone()
        try:
            geometry.transform(4326)
        except Exception as exc:
            raise InvalidGeometry(
                "Não foi possível transformar a geometria para EPSG:4326."
            ) from exc
    if not geometry.valid:
        logger.info("Normalizing invalid polygonal geometry with GEOS make_valid")
        geometry = geometry.make_valid()

    polygons = _polygon_parts(geometry)
    if not polygons:
        raise InvalidGeometry("A geometria deve conter ao menos um Polygon válido.")
    normalized = MultiPolygon(*polygons, srid=4326)
    if not normalized.valid:
        raise InvalidGeometry(f"Geometria inválida: {normalized.valid_reason}")

    xmin, ymin, xmax, ymax = normalized.extent
    if xmin < -180 or xmax > 180 or ymin < -90 or ymax > 90:
        raise InvalidGeometry(
            "A geometria possui coordenadas fora dos limites de EPSG:4326."
        )
    return normalized


def calculate_area_hectares(geometry: GEOSGeometry) -> float:
    normalized = normalize_multipolygon(geometry)
    equal_area = normalized.clone()
    equal_area.transform(6933)
    return round(equal_area.area / 10_000, 4)


def validate_area_limit(geometry: GEOSGeometry) -> float:
    area_hectares = calculate_area_hectares(geometry)
    maximum = settings.MAX_PROPERTY_AREA_HECTARES
    if maximum > 0 and area_hectares > maximum:
        raise InvalidGeometry(
            f"A área excede o limite configurado de {maximum:g} hectares."
        )
    return area_hectares
