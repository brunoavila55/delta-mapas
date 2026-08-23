import json
import logging
from dataclasses import dataclass
from typing import Literal

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.contrib.gis.geos.error import GEOSException

from .exceptions import InvalidGeometry
from .geometry_limits import validate_geojson_complexity

logger = logging.getLogger(__name__)

GeometryOperation = Literal["union", "cut"]


@dataclass(frozen=True)
class GeometryOperationResult:
    geometry: MultiPolygon
    area_hectares: float
    changed_area_hectares: float
    component_count: int


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


def parse_and_validate_geometry(
    value: object,
    *,
    enforce_area_limit: bool = True,
) -> MultiPolygon:
    """Parse GeoJSON and apply the domain rules used by every interface."""
    if isinstance(value, dict) and value.get("type") == "Feature":
        value = value.get("geometry")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise InvalidGeometry(
                "A geometria deve ser enviada como GeoJSON."
            ) from exc
    if not isinstance(value, dict):
        raise InvalidGeometry("A geometria deve ser enviada como GeoJSON.")

    try:
        validate_geojson_complexity(value)
        geometry = GEOSGeometry(json.dumps(value))
        normalized = normalize_multipolygon(geometry)
        if enforce_area_limit:
            validate_area_limit(normalized)
        return normalized
    except InvalidGeometry:
        raise
    except (GEOSException, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidGeometry(f"GeoJSON inválido: {exc}") from exc


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


def apply_geometry_operation(
    *,
    geometry: GEOSGeometry,
    operand: GEOSGeometry,
    operation: GeometryOperation,
) -> GeometryOperationResult:
    base = normalize_multipolygon(geometry)
    overlay = normalize_multipolygon(operand)

    if not base.intersects(overlay):
        raise InvalidGeometry(
            "A área desenhada precisa tocar ou cruzar a geometria atual."
        )

    if operation == "union":
        candidate = base.union(overlay)
    elif operation == "cut":
        candidate = base.difference(overlay)
        if candidate.empty:
            raise InvalidGeometry("O recorte não pode remover toda a geometria.")
    else:
        raise InvalidGeometry("Operação de geometria não suportada.")

    result = normalize_multipolygon(candidate)
    if result.equals(base):
        raise InvalidGeometry("A área desenhada não altera a geometria atual.")

    before_area = calculate_area_hectares(base)
    after_area = validate_area_limit(result)
    return GeometryOperationResult(
        geometry=result,
        area_hectares=after_area,
        changed_area_hectares=round(abs(after_area - before_area), 4),
        component_count=len(result),
    )
