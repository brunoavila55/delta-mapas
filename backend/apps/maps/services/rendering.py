from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib
import numpy as np
from django.conf import settings
from matplotlib import colors, patches, ticker
from numpy.typing import NDArray
from pyproj import CRS, Transformer

from ..exceptions import MapRenderingError
from .copernicus import CopernicusScene

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


NDVI_BOUNDS = (-1.0, -0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
NDVI_COLORS = (
    "#7f3b08",
    "#b35806",
    "#f1a340",
    "#fee08b",
    "#d9ef8b",
    "#66bd63",
    "#1a9850",
)


@dataclass(frozen=True, slots=True)
class RenderedMapFiles:
    png_path: Path
    pdf_path: Path
    metadata: dict[str, object]


def _nice_scale_length(width_meters: float) -> float:
    target = max(width_meters / 4, 1)
    magnitude = 10 ** math.floor(math.log10(target))
    normalized = target / magnitude
    multiplier = 1 if normalized < 2 else 2 if normalized < 5 else 5
    return multiplier * magnitude


def _format_scale(length_meters: float) -> str:
    if length_meters >= 1000:
        return f"{length_meters / 1000:g} km"
    return f"{length_meters:g} m"


def _draw_geometry_boundary(axis, geometry, crs: CRS) -> None:
    projected = geometry.clone()
    target_epsg = crs.to_epsg()
    if target_epsg is None:
        return
    if projected.srid != target_epsg:
        projected.transform(target_epsg)
    polygons = projected if projected.geom_type == "MultiPolygon" else (projected,)
    for polygon in polygons:
        coordinates = polygon.exterior_ring.coords
        x_values = [coordinate[0] for coordinate in coordinates]
        y_values = [coordinate[1] for coordinate in coordinates]
        axis.plot(
            x_values,
            y_values,
            color="#111827",
            linewidth=1.2,
            alpha=0.9,
            zorder=3,
        )


def _validate_render_input(
    data: NDArray[np.float32],
    valid_mask: NDArray[np.bool_],
    raster_metadata: dict[str, object],
) -> tuple[tuple[float, float, float, float], CRS]:
    if data.ndim != 2 or valid_mask.shape != data.shape:
        raise MapRenderingError("O índice e a máscara devem ter dimensões idênticas.")
    if not np.any(valid_mask):
        raise MapRenderingError("O índice não possui pixels válidos para renderização.")
    try:
        bounds_values = raster_metadata["bounds"]
        if not isinstance(bounds_values, (list, tuple)) or len(bounds_values) != 4:
            raise ValueError
        bounds = tuple(float(value) for value in bounds_values)
        crs = CRS.from_user_input(raster_metadata["crs"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MapRenderingError(
            "Os metadados espaciais do raster são inválidos."
        ) from exc
    if not all(math.isfinite(value) for value in bounds):
        raise MapRenderingError("Os limites espaciais do raster são inválidos.")
    if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        raise MapRenderingError("A extensão espacial do raster é vazia.")
    return bounds, crs


def render_index_map(
    *,
    data: NDArray[np.float32],
    valid_mask: NDArray[np.bool_],
    raster_metadata: dict[str, object],
    geometry,
    property_name: str,
    area_hectares,
    scene: CopernicusScene,
    generated_at: datetime,
    target_directory: Path | str,
) -> RenderedMapFiles:
    bounds, crs = _validate_render_input(data, valid_mask, raster_metadata)
    maximum_dimension = settings.MAP_RENDER_MAX_DIMENSION_PIXELS
    if maximum_dimension <= 0:
        raise MapRenderingError("O limite de dimensão da renderização é inválido.")

    step = max(1, math.ceil(max(data.shape) / maximum_dimension))
    display_data = data[::step, ::step]
    display_valid = valid_mask[::step, ::step] & np.isfinite(display_data)
    masked_data = np.ma.array(display_data, mask=~display_valid)
    target_directory = Path(target_directory)
    target_directory.mkdir(parents=True, exist_ok=True)
    png_path = target_directory / "map.png"
    pdf_path = target_directory / "map.pdf"

    cmap = colors.ListedColormap(NDVI_COLORS, name="delta_ndvi").with_extremes(
        bad="#e5e7eb"
    )
    norm = colors.BoundaryNorm(NDVI_BOUNDS, cmap.N, clip=True)

    figure = None
    try:
        figure = plt.figure(figsize=(11.69, 8.27), facecolor="#f8fafc")
        map_axis = figure.add_axes((0.07, 0.20, 0.68, 0.66), facecolor="#e5e7eb")
        info_axis = figure.add_axes((0.78, 0.20, 0.19, 0.66), facecolor="#ffffff")
        colorbar_axis = figure.add_axes((0.11, 0.105, 0.58, 0.028))

        xmin, ymin, xmax, ymax = bounds
        image = map_axis.imshow(
            masked_data,
            extent=(xmin, xmax, ymin, ymax),
            origin="upper",
            cmap=cmap,
            norm=norm,
            interpolation="nearest",
            rasterized=True,
            zorder=1,
        )
        _draw_geometry_boundary(map_axis, geometry, crs)
        map_axis.set_xlim(xmin, xmax)
        map_axis.set_ylim(ymin, ymax)
        map_axis.set_aspect("equal", adjustable="box")
        map_axis.grid(color="#ffffff", linewidth=0.6, alpha=0.75)
        map_axis.set_xlabel("Longitude", fontsize=8, labelpad=8)
        map_axis.set_ylabel("Latitude", fontsize=8, labelpad=8)

        transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        center_x = (xmin + xmax) / 2
        center_y = (ymin + ymax) / 2
        map_axis.xaxis.set_major_locator(ticker.MaxNLocator(5))
        map_axis.yaxis.set_major_locator(ticker.MaxNLocator(5))
        map_axis.xaxis.set_major_formatter(
            ticker.FuncFormatter(
                lambda value, _position: f"{transformer.transform(value, center_y)[0]:.5f}°"
            )
        )
        map_axis.yaxis.set_major_formatter(
            ticker.FuncFormatter(
                lambda value, _position: f"{transformer.transform(center_x, value)[1]:.5f}°"
            )
        )
        map_axis.tick_params(labelsize=7)
        map_axis.xaxis.get_offset_text().set_visible(False)
        map_axis.yaxis.get_offset_text().set_visible(False)

        scale_length = _nice_scale_length(xmax - xmin)
        scale_x = xmin + (xmax - xmin) * 0.07
        scale_y = ymin + (ymax - ymin) * 0.07
        map_axis.plot(
            (scale_x, scale_x + scale_length),
            (scale_y, scale_y),
            color="#111827",
            linewidth=4,
            solid_capstyle="butt",
            zorder=4,
        )
        map_axis.plot(
            (scale_x, scale_x + scale_length),
            (scale_y, scale_y),
            color="#ffffff",
            linewidth=1.5,
            solid_capstyle="butt",
            zorder=5,
        )
        map_axis.text(
            scale_x + scale_length / 2,
            scale_y + (ymax - ymin) * 0.025,
            _format_scale(scale_length),
            ha="center",
            va="bottom",
            fontsize=7,
            weight="bold",
            zorder=5,
        )
        map_axis.annotate(
            "N",
            xy=(0.94, 0.91),
            xytext=(0.94, 0.78),
            xycoords="axes fraction",
            ha="center",
            va="center",
            fontsize=10,
            weight="bold",
            arrowprops={"facecolor": "#111827", "width": 3, "headwidth": 10},
            zorder=6,
        )

        colorbar = figure.colorbar(
            image,
            cax=colorbar_axis,
            orientation="horizontal",
            boundaries=NDVI_BOUNDS,
            ticks=NDVI_BOUNDS,
            spacing="proportional",
        )
        colorbar.ax.tick_params(labelsize=7)
        colorbar.set_label(
            "Índice de Vegetação por Diferença Normalizada (NDVI)", fontsize=8
        )

        valid_values = data[valid_mask & np.isfinite(data)]
        info_axis.set_xticks(())
        info_axis.set_yticks(())
        for spine in info_axis.spines.values():
            spine.set_color("#cbd5e1")
        property_label = property_name or "Área avulsa"
        area_label = (
            f"{float(area_hectares):,.2f} ha" if area_hectares is not None else "—"
        )
        scene_date = scene.acquired_at.astimezone().strftime("%d/%m/%Y %H:%M")
        generated_label = generated_at.astimezone().strftime("%d/%m/%Y %H:%M")
        details = (
            ("PROPRIEDADE", property_label),
            ("ÍNDICE", "NDVI"),
            ("ÁREA", area_label),
            ("CENA", scene_date),
            ("SATÉLITE", scene.platform.replace("-", " ").title()),
            ("COBERTURA DE NUVENS", f"{scene.cloud_cover}%"),
            ("NDVI MÍNIMO", f"{float(np.min(valid_values)):.3f}"),
            ("NDVI MÉDIO", f"{float(np.mean(valid_values)):.3f}"),
            ("NDVI MÁXIMO", f"{float(np.max(valid_values)):.3f}"),
            ("PROJEÇÃO", crs.to_string()),
            ("GERADO EM", generated_label),
        )
        y_position = 0.96
        for label, value in details:
            info_axis.text(
                0.07,
                y_position,
                label,
                transform=info_axis.transAxes,
                fontsize=6.5,
                color="#64748b",
                weight="bold",
                va="top",
            )
            info_axis.text(
                0.07,
                y_position - 0.035,
                value,
                transform=info_axis.transAxes,
                fontsize=8,
                color="#0f172a",
                va="top",
                wrap=True,
            )
            y_position -= 0.085

        logo_mark = patches.Polygon(
            ((0.07, 0.925), (0.083, 0.965), (0.096, 0.925)),
            closed=True,
            transform=figure.transFigure,
            facecolor="#16a34a",
            edgecolor="none",
        )
        figure.add_artist(logo_mark)
        figure.text(
            0.105, 0.945, "DELTA MAPAS", fontsize=16, weight="bold", color="#0f172a"
        )
        figure.text(
            0.105, 0.918, "Sensoriamento remoto agrícola", fontsize=8, color="#64748b"
        )
        figure.text(
            0.74,
            0.946,
            "MAPA DE NDVI",
            fontsize=16,
            weight="bold",
            ha="right",
            color="#166534",
        )
        figure.text(
            0.74, 0.918, property_label, fontsize=9, ha="right", color="#334155"
        )
        figure.text(
            0.07,
            0.035,
            "Fonte: Copernicus Data Space Ecosystem · Sentinel-2 Level-2A · Máscara de nuvens SCL",
            fontsize=7,
            color="#64748b",
        )
        figure.text(
            0.97,
            0.035,
            f"STAC: {scene.item_id}",
            fontsize=6,
            color="#94a3b8",
            ha="right",
        )

        figure.savefig(
            png_path,
            format="png",
            dpi=settings.MAP_RENDER_PNG_DPI,
            facecolor=figure.get_facecolor(),
            metadata={
                "Title": f"Mapa NDVI — {property_label}",
                "Software": "Delta Mapas",
            },
        )
        figure.savefig(
            pdf_path,
            format="pdf",
            dpi=settings.MAP_RENDER_PDF_DPI,
            facecolor=figure.get_facecolor(),
            metadata={
                "Title": f"Mapa NDVI — {property_label}",
                "Author": "Delta Mapas",
                "Subject": "Mapa de sensoriamento remoto Sentinel-2 L2A",
            },
        )
    except MapRenderingError:
        raise
    except Exception as exc:
        raise MapRenderingError("Não foi possível compor o mapa cartográfico.") from exc
    finally:
        if figure is not None:
            plt.close(figure)

    if not png_path.is_file() or not pdf_path.is_file():
        raise MapRenderingError("Os produtos cartográficos não foram gerados.")
    return RenderedMapFiles(
        png_path=png_path,
        pdf_path=pdf_path,
        metadata={
            "renderer": "matplotlib",
            "template": "ndvi-a4-landscape-v1",
            "source_shape": list(data.shape),
            "render_shape": list(display_data.shape),
            "downsample_step": step,
            "png_size_bytes": png_path.stat().st_size,
            "pdf_size_bytes": pdf_path.stat().st_size,
        },
    )
