use anyhow::{Context, Result, bail, ensure};
use geo::{BoundingRect, Contains, Geometry, MultiPolygon, Point, Validation};
use geojson::GeoJson;
use serde_json::Value;
use std::{fs, path::Path};

/// MVP accepts WGS84 polygonal areas without crossing the antimeridian.
pub struct Area {
    pub polygons: MultiPolygon<f64>,
    pub geometry: Value,
    pub bounds: [f64; 4],
}

impl Area {
    pub fn read(path: &Path) -> Result<Self> {
        ensure!(
            fs::metadata(path)?.len() <= 2_000_000,
            "GeoJSON excede 2 MB"
        );
        let input = fs::read_to_string(path)?;
        Self::from_json(&input)
    }

    pub fn from_json(input: &str) -> Result<Self> {
        ensure!(input.len() <= 2_000_000, "GeoJSON excede 2 MB");
        ensure!(
            !serde_json::from_str::<Value>(input)?
                .as_object()
                .is_some_and(|v| v.contains_key("crs")),
            "Use GeoJSON RFC 7946 em WGS84, sem CRS legado"
        );
        let parsed: GeoJson = input.parse().context("GeoJSON inválido")?;
        let geometry = match parsed {
            GeoJson::Geometry(g) => g,
            GeoJson::Feature(f) => f.geometry.context("Feature sem geometria")?,
            _ => {
                bail!("Informe uma Geometry ou Feature; FeatureCollection não é aceita nesta prova")
            }
        };
        let value = serde_json::to_value(&geometry)?;
        // geo::Polygon closes rings during conversion. Validate the original
        // input first so the sent geometry and the local mask cannot disagree.
        let rings: Vec<&Vec<Vec<f64>>> = match &geometry.value {
            geojson::Value::Polygon(rings) => rings.iter().collect(),
            geojson::Value::MultiPolygon(polygons) => polygons.iter().flatten().collect(),
            _ => bail!("A área deve ser Polygon ou MultiPolygon"),
        };
        for ring in rings {
            ensure!(
                ring.len() >= 4 && ring.first() == ring.last(),
                "Anel GeoJSON aberto ou incompleto"
            );
        }
        let decoded: Geometry<f64> = geometry.value.try_into()?;
        let polygons = match decoded {
            Geometry::Polygon(p) => MultiPolygon(vec![p]),
            Geometry::MultiPolygon(p) => p,
            _ => bail!("A área deve ser Polygon ou MultiPolygon"),
        };
        ensure!(!polygons.0.is_empty(), "Área vazia");
        let mut count = 0;
        for p in &polygons.0 {
            for ring in std::iter::once(p.exterior()).chain(p.interiors()) {
                ensure!(
                    ring.0.len() >= 4 && ring.0.first() == ring.0.last(),
                    "Anel inválido ou aberto"
                );
                for c in &ring.0 {
                    count += 1;
                    ensure!(
                        c.x.is_finite()
                            && c.y.is_finite()
                            && (-180.0..=180.0).contains(&c.x)
                            && (-80.0..=84.0).contains(&c.y),
                        "Coordenada fora da faixa suportada"
                    );
                }
            }
        }
        ensure!(count <= 10_000, "Área excede 10.000 coordenadas");
        polygons
            .check_validation()
            .map_err(|e| anyhow::anyhow!("Geometria inválida: {e}"))?;
        let rect = polygons.bounding_rect().context("Área vazia")?;
        let bounds = [rect.min().x, rect.min().y, rect.max().x, rect.max().y];
        ensure!(
            bounds[2] > bounds[0] && bounds[3] > bounds[1],
            "Área sem extensão"
        );
        ensure!(
            bounds[2] - bounds[0] <= 1.0 && bounds[3] - bounds[1] <= 1.0,
            "Nesta prova, a área deve caber em uma caixa de até 1 grau por eixo"
        );
        Ok(Self {
            polygons,
            geometry: value,
            bounds,
        })
    }

    /// Database snapshots are SIRGAS 2000; provider/mask coordinates are WGS84.
    pub fn from_sirgas_json(input: &str) -> Result<Self> {
        ensure!(input.len() <= 2_000_000, "Geometria excede 2 MB");
        let value: Value = serde_json::from_str(input)?;
        let value = crate::crs::geometry(&value, crate::crs::SIRGAS2000, crate::crs::WGS84)?;
        Self::from_json(&value.to_string())
    }

    pub fn sirgas_geometry(&self) -> Result<Value> {
        crate::crs::geometry(&self.geometry, crate::crs::WGS84, crate::crs::SIRGAS2000)
    }

    pub fn sirgas_area_ha(&self) -> Result<f64> {
        use geo::MapCoords;
        use geographiclib_rs::{Geodesic, PolygonArea, Winding};
        let transform = crate::crs::Transform::new(crate::crs::WGS84, crate::crs::SIRGAS2000)?;
        let polygons = self
            .polygons
            .try_map_coords(|c| -> Result<geo::Coord<f64>> {
                let (x, y) = transform.point(c.x, c.y)?;
                Ok(geo::Coord { x, y })
            })?;
        let ellipsoid = Geodesic::new(6_378_137.0, 1.0 / 298.257_222_101);
        let ring_area = |ring: &geo::LineString<f64>| {
            let mut polygon = PolygonArea::new(&ellipsoid, Winding::CounterClockwise);
            for point in ring.points() {
                polygon.add_point(point.y(), point.x());
            }
            polygon.compute(true).1.abs()
        };
        Ok(polygons
            .0
            .iter()
            .map(|p| ring_area(p.exterior()) - p.interiors().iter().map(ring_area).sum::<f64>())
            .sum::<f64>()
            / 10_000.0)
    }

    pub fn contains(&self, lon: f64, lat: f64) -> bool {
        self.polygons.contains(&Point::new(lon, lat))
    }

    pub fn grid_size(&self, resolution_m: f64) -> Result<(u32, u32)> {
        ensure!(
            resolution_m.is_finite() && resolution_m >= 10.0,
            "Resolução mínima: 10 metros"
        );
        let [west, south, east, north] = self.bounds;
        let middle_lat = (south + north) / 2.0;
        // Approximate sizing only; actual geographic pixel size is preserved in GeoTIFF.
        let width = ((east - west) * 111_320.0 * middle_lat.to_radians().cos() / resolution_m)
            .ceil() as u32;
        let height = ((north - south) * 111_320.0 / resolution_m).ceil() as u32;
        ensure!(
            width > 0
                && height > 0
                && width <= 2500
                && height <= 2500
                && u64::from(width) * u64::from(height) <= 4_000_000,
            "Grade excede os limites: 2.500 pixels por eixo e 4 milhões de pixels"
        );
        Ok((width, height))
    }
}
