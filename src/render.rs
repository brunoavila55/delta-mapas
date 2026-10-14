use crate::{
    area::Area,
    raster::{Analysis, NODATA},
};
use anyhow::Result;
use image::{Rgb, RgbImage};
use serde_json::Value;
use std::{fs, path::Path};

pub const COLORS: [[u8; 3]; 7] = [
    [153, 63, 38],
    [210, 120, 54],
    [244, 185, 88],
    [242, 222, 141],
    [177, 209, 120],
    [79, 157, 88],
    [24, 101, 65],
];
pub const BOUNDS: [f32; 8] = [-1.0, -0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0];

pub fn color(value: f32) -> [u8; 3] {
    let bucket = (0..7).find(|&i| value < BOUNDS[i + 1]).unwrap_or(6);
    COLORS[bucket]
}

pub fn map_image(analysis: &Analysis, area: &Area) -> Result<RgbImage> {
    let g = analysis.grid;
    let transform = crate::crs::Transform::new(g.epsg, crate::crs::WGS84)?;
    Ok(RgbImage::from_fn(g.width, g.height, |x, y| {
        let value = analysis.ndvi[(y * g.width + x) as usize];
        let (x, y) = g.center(x, y);
        let inside = transform
            .point(x, y)
            .is_ok_and(|(lon, lat)| area.contains(lon, lat));
        Rgb(if !inside {
            [250, 251, 248]
        } else if value == NODATA {
            [204, 210, 210]
        } else {
            color(value)
        })
    }))
}

pub fn write_products(
    directory: &Path,
    analysis: &Analysis,
    area: &Area,
    mut source: Value,
) -> Result<()> {
    let export = crate::raster::export_sirgas(analysis, area, 10.0)?;
    let map = map_image(&export, area)?;
    map.save(directory.join("ndvi.png"))?;
    crate::raster::write_ndvi(&directory.join("ndvi.tif"), &export)?;
    source["generated_at"] =
        serde_json::json!(chrono::Utc::now().format("%Y-%m-%d %H:%M").to_string());
    let distribution =
        crate::cartography::write_documents(directory, &map, &export, analysis, area, &source)?;
    let metadata = serde_json::json!({
        "schema_version": 3, "pipeline_version": "ndvi-v3-cartography", "index": "NDVI",
        "created_at": chrono::Utc::now(), "source": source,
        "grid": export.grid, "crs": format!("EPSG:{}", export.grid.epsg), "nodata": NODATA,
        "processing_grid": analysis.grid, "processing_crs": "EPSG:4326",
        "statistics_grid": "processing_grid", "resampling": "nearest",
        "geometry": area.geometry, "geometry_crs": "EPSG:4326",
        "cadastral_geometry": area.sirgas_geometry()?, "cadastral_crs": "EPSG:4674", "area_ha": area.sirgas_area_ha()?,
        "statistics": analysis.statistics,
        "mask_policy": {"accepted_scl": [4,5,6], "data_mask": 1, "minimum_band_sum": 1e-6},
        "legend": {"bounds": BOUNDS, "rgb": COLORS},
        "distribution": distribution,
        "products": ["ndvi.tif", "ndvi.png", "map.pdf", "report.pdf"]
    });
    fs::write(
        directory.join("analysis.json"),
        serde_json::to_vec_pretty(&metadata)?,
    )?;
    Ok(())
}
