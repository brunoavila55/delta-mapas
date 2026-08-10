from __future__ import annotations

import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import geopandas as gpd
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from shapely import make_valid, to_geojson, union_all
from shapely.geometry import GeometryCollection, MultiPolygon as ShapelyMultiPolygon
from shapely.geometry import Polygon as ShapelyPolygon

from .exceptions import InvalidShapefile
from .services import normalize_multipolygon, validate_area_limit

ALLOWED_EXTENSIONS = {
    ".shp",
    ".shx",
    ".dbf",
    ".prj",
    ".cpg",
    ".qix",
    ".sbn",
    ".sbx",
    ".fbn",
    ".fbx",
    ".ain",
    ".aih",
    ".atx",
    ".ixs",
    ".mxs",
    ".xml",
}
REQUIRED_EXTENSIONS = {".shp", ".shx", ".dbf", ".prj"}


def _safe_member_path(root: Path, filename: str) -> Path:
    normalized_name = filename.replace("\\", "/")
    relative = PurePosixPath(normalized_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise InvalidShapefile("O ZIP contém um caminho inseguro.")
    if relative.parts and ":" in relative.parts[0]:
        raise InvalidShapefile("O ZIP contém um caminho absoluto inválido.")

    target = (root / Path(*relative.parts)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise InvalidShapefile(
            "O ZIP tenta gravar fora do diretório temporário."
        ) from exc
    return target


def _validate_archive(
    archive: zipfile.ZipFile, extraction_root: Path
) -> list[zipfile.ZipInfo]:
    files = [info for info in archive.infolist() if not info.is_dir()]
    if not files or len(files) > settings.SHAPEFILE_MAX_FILES:
        raise InvalidShapefile("Quantidade de arquivos inválida no ZIP.")

    total_size = 0
    for info in files:
        _safe_member_path(extraction_root, info.filename)
        extension = Path(info.filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise InvalidShapefile(
                f"Arquivo não permitido no ZIP: {extension or 'sem extensão'}."
            )
        if info.flag_bits & 0x1:
            raise InvalidShapefile("Arquivos ZIP criptografados não são aceitos.")
        file_type = (info.external_attr >> 16) & 0o170000
        if file_type == stat.S_IFLNK:
            raise InvalidShapefile("Links simbólicos não são aceitos no ZIP.")

        total_size += info.file_size
        if total_size > settings.SHAPEFILE_MAX_UNCOMPRESSED_BYTES:
            raise InvalidShapefile(
                "O conteúdo descompactado excede o limite permitido."
            )
        if info.file_size and not info.compress_size:
            raise InvalidShapefile("O ZIP possui uma taxa de compressão inválida.")
        if info.compress_size:
            ratio = info.file_size / info.compress_size
            if ratio > settings.SHAPEFILE_MAX_COMPRESSION_RATIO:
                raise InvalidShapefile("O ZIP possui uma taxa de compressão suspeita.")
    return files


def _extract_archive(
    archive: zipfile.ZipFile, files: list[zipfile.ZipInfo], root: Path
) -> None:
    total_written = 0
    for info in files:
        target = _safe_member_path(root, info.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info, "r") as source, target.open("wb") as destination:
            while chunk := source.read(1024 * 1024):
                total_written += len(chunk)
                if total_written > settings.SHAPEFILE_MAX_UNCOMPRESSED_BYTES:
                    raise InvalidShapefile(
                        "O conteúdo extraído excede o limite permitido."
                    )
                destination.write(chunk)


def _find_shapefile(root: Path) -> Path:
    shapefiles = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() == ".shp"
    ]
    if len(shapefiles) != 1:
        raise InvalidShapefile("O ZIP deve conter exatamente um arquivo .shp.")

    shapefile = shapefiles[0]
    siblings = {
        path.suffix.lower()
        for path in shapefile.parent.iterdir()
        if path.is_file() and path.stem.lower() == shapefile.stem.lower()
    }
    missing = REQUIRED_EXTENSIONS - siblings
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise InvalidShapefile(f"Componentes obrigatórios ausentes: {missing_text}.")
    return shapefile


def _polygon_parts(geometry) -> list[ShapelyPolygon]:
    if isinstance(geometry, ShapelyPolygon):
        return [geometry]
    if isinstance(geometry, (ShapelyMultiPolygon, GeometryCollection)):
        parts: list[ShapelyPolygon] = []
        for child in geometry.geoms:
            parts.extend(_polygon_parts(child))
        return parts
    return []


def _read_geometry(shapefile: Path) -> MultiPolygon:
    try:
        frame = gpd.read_file(shapefile, columns=[], engine="pyogrio")
    except Exception as exc:
        raise InvalidShapefile("Não foi possível ler o shapefile enviado.") from exc
    if frame.crs is None:
        raise InvalidShapefile("O shapefile não informa um CRS válido no arquivo .prj.")
    if len(frame.index) > settings.SHAPEFILE_MAX_FEATURES:
        raise InvalidShapefile("O shapefile excede o limite de feições permitido.")

    try:
        frame = frame.to_crs(epsg=4326)
    except Exception as exc:
        raise InvalidShapefile(
            "Não foi possível transformar o shapefile para EPSG:4326."
        ) from exc

    polygons: list[ShapelyPolygon] = []
    for geometry in frame.geometry:
        if geometry is None or geometry.is_empty:
            continue
        repaired = make_valid(geometry) if not geometry.is_valid else geometry
        polygons.extend(_polygon_parts(repaired))
    if not polygons:
        raise InvalidShapefile("O shapefile não contém geometrias poligonais válidas.")

    merged = union_all(polygons)
    try:
        geometry = GEOSGeometry(to_geojson(merged), srid=4326)
        normalized = normalize_multipolygon(geometry)
        validate_area_limit(normalized)
    except Exception as exc:
        if isinstance(exc, InvalidShapefile):
            raise
        raise InvalidShapefile(
            "A geometria resultante do shapefile é inválida."
        ) from exc
    return normalized


def import_shapefile(uploaded_file) -> MultiPolygon:
    if uploaded_file.size > settings.SHAPEFILE_MAX_UPLOAD_BYTES:
        raise InvalidShapefile("O arquivo excede o limite de upload permitido.")

    with tempfile.TemporaryDirectory(prefix="delta-mapas-shapefile-") as temporary:
        temporary_root = Path(temporary)
        archive_path = temporary_root / "upload.zip"
        extracted_root = temporary_root / "extracted"
        extracted_root.mkdir()

        size = 0
        with archive_path.open("wb") as destination:
            for chunk in uploaded_file.chunks():
                size += len(chunk)
                if size > settings.SHAPEFILE_MAX_UPLOAD_BYTES:
                    raise InvalidShapefile(
                        "O arquivo excede o limite de upload permitido."
                    )
                destination.write(chunk)

        if not zipfile.is_zipfile(archive_path):
            raise InvalidShapefile("O arquivo enviado não é um ZIP válido.")
        try:
            with zipfile.ZipFile(archive_path) as archive:
                files = _validate_archive(archive, extracted_root)
                _extract_archive(archive, files, extracted_root)
        except zipfile.BadZipFile as exc:
            raise InvalidShapefile("O arquivo ZIP está corrompido.") from exc

        shapefile = _find_shapefile(extracted_root)
        return _read_geometry(shapefile)
