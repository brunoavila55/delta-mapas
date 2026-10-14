//! Explicit CRS boundaries: browser/provider WGS84, cadastral SIRGAS 2000,
//! and metric SIRGAS 2000 / UTM exports. proj4rs uses radians for longlat.
use anyhow::{Result, ensure};
use proj4rs::Proj;
use serde_json::Value;

pub const WGS84: u16 = 4326;
pub const SIRGAS2000: u16 = 4674;

pub struct Transform {
    source: Proj,
    target: Proj,
}

fn definition(epsg: u16) -> Result<String> {
    Ok(match epsg {
        WGS84 => "+proj=longlat +datum=WGS84 +no_defs".into(),
        SIRGAS2000 => "+proj=longlat +ellps=GRS80 +towgs84=0,0,0 +no_defs".into(),
        31972..=31976 => format!(
            "+proj=utm +zone={} +ellps=GRS80 +towgs84=0,0,0 +units=m +no_defs",
            epsg - 31954
        ),
        31978..=31985 => format!(
            "+proj=utm +zone={} +south +ellps=GRS80 +towgs84=0,0,0 +units=m +no_defs",
            epsg - 31960
        ),
        _ => anyhow::bail!("CRS não suportado: EPSG:{epsg}"),
    })
}

impl Transform {
    pub fn new(source: u16, target: u16) -> Result<Self> {
        Ok(Self {
            source: Proj::from_proj_string(&definition(source)?)?,
            target: Proj::from_proj_string(&definition(target)?)?,
        })
    }

    pub fn point(&self, x: f64, y: f64) -> Result<(f64, f64)> {
        ensure!(x.is_finite() && y.is_finite(), "Coordenada inválida");
        let input = if self.source.is_latlong() {
            (x.to_radians(), y.to_radians())
        } else {
            (x, y)
        };
        let (x, y) = proj4rs::adaptors::transform_vertex_2d(&self.source, &self.target, input)?;
        let result = if self.target.is_latlong() {
            (x.to_degrees(), y.to_degrees())
        } else {
            (x, y)
        };
        ensure!(
            result.0.is_finite() && result.1.is_finite(),
            "Transformação inválida"
        );
        Ok(result)
    }
}

/// Transforms coordinates without changing Polygon/MultiPolygon structure.
/// Internal SIRGAS JSON is accompanied by geometry_crs; public GeoJSON is WGS84.
pub fn geometry(value: &Value, source: u16, target: u16) -> Result<Value> {
    let mut output = value.clone();
    let depth = match output["type"].as_str() {
        Some("Polygon") => 2,
        Some("MultiPolygon") => 3,
        _ => anyhow::bail!("Geometria poligonal necessária"),
    };
    fn coordinates(value: &mut Value, depth: usize, transform: &Transform) -> Result<()> {
        let items = value
            .as_array_mut()
            .ok_or_else(|| anyhow::anyhow!("Coordenadas inválidas"))?;
        if depth == 0 {
            ensure!(items.len() >= 2, "Coordenada incompleta");
            let (x, y) = transform.point(
                items[0]
                    .as_f64()
                    .ok_or_else(|| anyhow::anyhow!("Longitude inválida"))?,
                items[1]
                    .as_f64()
                    .ok_or_else(|| anyhow::anyhow!("Latitude inválida"))?,
            )?;
            items[0] = Value::from(x);
            items[1] = Value::from(y);
        } else {
            for item in items {
                coordinates(item, depth - 1, transform)?;
            }
        }
        Ok(())
    }
    coordinates(
        &mut output["coordinates"],
        depth,
        &Transform::new(source, target)?,
    )?;
    Ok(output)
}

pub fn sirgas_utm(longitude: f64, latitude: f64) -> Result<u16> {
    ensure!(
        longitude.is_finite() && latitude.is_finite() && (-80.0..=84.0).contains(&latitude),
        "Localização UTM inválida"
    );
    let zone = ((longitude + 180.0) / 6.0).floor() as i32 + 1;
    ensure!(
        (18..=25).contains(&zone) && (latitude < 0.0 || zone <= 22),
        "Exportação SIRGAS/UTM limitada aos fusos brasileiros 18–25S e 18–22N"
    );
    Ok(if latitude < 0.0 {
        31960 + zone as u16
    } else {
        31954 + zone as u16
    })
}
