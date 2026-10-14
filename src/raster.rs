use crate::area::Area;
use anyhow::{Context, Result, bail, ensure};
use serde::Serialize;
use std::{
    fs::File,
    io::{BufReader, BufWriter},
    path::Path,
};
use tiff::{
    decoder::{Decoder, DecodingResult, Limits},
    encoder::{TiffEncoder, colortype},
    tags::Tag,
};

pub const MAX_PIXELS: u64 = 4_000_000;
pub const NODATA: f32 = -9999.0;

#[derive(Clone, Copy, Debug, Serialize)]
pub struct Grid {
    pub epsg: u16,
    pub width: u32,
    pub height: u32,
    pub west: f64,
    pub north: f64,
    pub dx: f64,
    pub dy: f64,
}

impl Grid {
    pub fn from_area(area: &Area, width: u32, height: u32) -> Self {
        Self {
            epsg: crate::crs::WGS84,
            width,
            height,
            west: area.bounds[0],
            north: area.bounds[3],
            dx: (area.bounds[2] - area.bounds[0]) / f64::from(width),
            dy: (area.bounds[3] - area.bounds[1]) / f64::from(height),
        }
    }
    pub fn center(&self, column: u32, row: u32) -> (f64, f64) {
        (
            self.west + (f64::from(column) + 0.5) * self.dx,
            self.north - (f64::from(row) + 0.5) * self.dy,
        )
    }
    pub fn validate(&self) -> Result<()> {
        ensure!(
            self.epsg == crate::crs::WGS84,
            "Bandas de processamento devem usar EPSG:4326"
        );
        ensure!(
            self.width > 0
                && self.height > 0
                && u64::from(self.width) * u64::from(self.height) <= MAX_PIXELS,
            "Dimensões raster fora do limite"
        );
        ensure!(
            [self.west, self.north, self.dx, self.dy]
                .iter()
                .all(|x| x.is_finite())
                && self.dx > 0.0
                && self.dy > 0.0,
            "Grade geográfica inválida"
        );
        ensure!(
            self.west >= -180.0
                && self.north <= 90.0
                && self.west + f64::from(self.width) * self.dx <= 180.0
                && self.north - f64::from(self.height) * self.dy >= -90.0,
            "Grade fora de WGS84"
        );
        Ok(())
    }
}

pub struct Bands {
    pub grid: Grid,
    /// Interleaved reflectance B04, B08, classification SCL and dataMask.
    pub samples: Vec<f32>,
}

#[derive(Clone, Debug, Serialize)]
pub struct Statistics {
    pub pixels_in_area: u64,
    pub valid_pixels: u64,
    pub valid_percent: f64,
    pub minimum: f32,
    pub maximum: f32,
    pub mean: f64,
}

pub struct Analysis {
    pub grid: Grid,
    pub ndvi: Vec<f32>,
    pub statistics: Statistics,
}

/// Conservative policy: vegetation, bare soil and water only. Clouds, shadows,
/// snow, unclassified, saturated and missing observations are rejected.
pub fn pixel_ndvi(red: f32, nir: f32, scl: f32, mask: f32) -> Option<f32> {
    if ![red, nir, scl, mask].iter().all(|x| x.is_finite())
        || mask != 1.0
        || ![4.0, 5.0, 6.0].contains(&scl)
        || red < 0.0
        || nir < 0.0
    {
        return None;
    }
    let sum = f64::from(nir) + f64::from(red);
    if sum <= 1e-6 {
        return None;
    }
    Some(((f64::from(nir) - f64::from(red)) / sum) as f32)
}

pub fn calculate(bands: &Bands, area: &Area) -> Result<Analysis> {
    bands.grid.validate()?;
    let size = (u64::from(bands.grid.width) * u64::from(bands.grid.height)) as usize;
    ensure!(
        bands.samples.len() == size * 4,
        "Quantidade de amostras incompatível com quatro bandas"
    );
    let mut ndvi = vec![NODATA; size];
    let (mut inside, mut valid, mut sum) = (0_u64, 0_u64, 0.0_f64);
    let (mut minimum, mut maximum) = (f32::INFINITY, f32::NEG_INFINITY);
    for (index, (pixel, output)) in bands
        .samples
        .as_chunks::<4>()
        .0
        .iter()
        .zip(ndvi.iter_mut())
        .enumerate()
    {
        let (lon, lat) = bands.grid.center(
            index as u32 % bands.grid.width,
            index as u32 / bands.grid.width,
        );
        if !area.contains(lon, lat) {
            continue;
        }
        inside += 1;
        if let Some(value) = pixel_ndvi(pixel[0], pixel[1], pixel[2], pixel[3]) {
            *output = value;
            valid += 1;
            sum += f64::from(value);
            minimum = minimum.min(value);
            maximum = maximum.max(value);
        }
    }
    ensure!(
        inside > 0,
        "Nenhum centro de pixel está dentro da área; verifique resolução e sobreposição"
    );
    ensure!(
        valid > 0,
        "Nenhum pixel válido na área após máscaras de nuvens e nodata"
    );
    Ok(Analysis {
        grid: bands.grid,
        ndvi,
        statistics: Statistics {
            pixels_in_area: inside,
            valid_pixels: valid,
            valid_percent: valid as f64 * 100.0 / inside as f64,
            minimum,
            maximum,
            mean: sum / valid as f64,
        },
    })
}

fn key(keys: &[u16], wanted: u16) -> Option<u16> {
    keys.get(4..)?
        .as_chunks::<4>()
        .0
        .iter()
        .find_map(|k| (k[0] == wanted && k[1] == 0 && k[2] == 1).then_some(k[3]))
}

pub fn read_bands(path: &Path) -> Result<Bands> {
    ensure!(
        std::fs::metadata(path)?.len() <= 80_000_000,
        "TIFF excede 80 MB"
    );
    let mut limits = Limits::default();
    limits.decoding_buffer_size = 64_000_000;
    limits.intermediate_buffer_size = 64_000_000;
    let mut reader = Decoder::new(BufReader::new(File::open(path)?))?.with_limits(limits);
    let (width, height) = reader.dimensions()?;
    ensure!(
        width > 0 && height > 0 && u64::from(width) * u64::from(height) <= MAX_PIXELS,
        "TIFF excede o limite de pixels"
    );
    ensure!(
        reader.get_tag_u32(Tag::SamplesPerPixel)? == 4,
        "TIFF deve ter quatro bandas B04/B08/SCL/dataMask"
    );
    ensure!(
        reader.find_tag(Tag::ModelTransformationTag)?.is_none(),
        "Grades rotacionadas não são suportadas nesta prova"
    );
    if let Some(orientation) = reader.find_tag(Tag::Orientation)? {
        ensure!(
            orientation.into_u32()? == 1,
            "Orientação TIFF não suportada"
        );
    }
    if let Some(configuration) = reader.find_tag(Tag::PlanarConfiguration)? {
        ensure!(
            configuration.into_u32()? == 1,
            "As bandas precisam estar intercaladas"
        );
    }
    let keys = reader
        .get_tag_u16_vec(Tag::GeoKeyDirectoryTag)
        .context("TIFF sem CRS")?;
    ensure!(
        key(&keys, 1024) == Some(2)
            && key(&keys, 2048) == Some(4326)
            && key(&keys, 1025) == Some(1),
        "Esta prova aceita apenas WGS84 EPSG:4326, PixelIsArea"
    );
    let scale = reader.get_tag_f64_vec(Tag::ModelPixelScaleTag)?;
    let tie = reader.get_tag_f64_vec(Tag::ModelTiepointTag)?;
    ensure!(
        scale.len() == 3 && tie.len() == 6 && tie.iter().all(|v| v.is_finite()),
        "Georreferência TIFF inválida"
    );
    let grid = Grid {
        epsg: crate::crs::WGS84,
        width,
        height,
        west: tie[3] - tie[0] * scale[0],
        north: tie[4] + tie[1] * scale[1],
        dx: scale[0],
        dy: scale[1],
    };
    grid.validate()?;
    let DecodingResult::F32(samples) = reader.read_image()? else {
        bail!("TIFF deve conter bandas Float32 em reflectância, sem escala DN");
    };
    ensure!(
        !reader.more_images(),
        "TIFF com múltiplas páginas não é suportado"
    );
    Ok(Bands { grid, samples })
}

pub fn write_ndvi(path: &Path, analysis: &Analysis) -> Result<()> {
    let g = analysis.grid;
    let mut encoder = TiffEncoder::new(BufWriter::new(File::create(path)?))?;
    let mut image = encoder.new_image::<colortype::Gray32Float>(g.width, g.height)?;
    image
        .encoder()
        .write_tag(Tag::ModelPixelScaleTag, &[g.dx, g.dy, 0.0][..])?;
    image.encoder().write_tag(
        Tag::ModelTiepointTag,
        &[0.0, 0.0, 0.0, g.west, g.north, 0.0][..],
    )?;
    image
        .encoder()
        .write_tag(Tag::GeoKeyDirectoryTag, &geokeys(g.epsg)?[..])?;
    image.encoder().write_tag(Tag::Unknown(42113), "-9999")?;
    image.encoder().write_tag(
        Tag::ImageDescription,
        "NDVI; nodata=-9999; pipeline=ndvi-v2-sirgas; resampling=nearest",
    )?;
    image.write_data(&analysis.ndvi)?;
    Ok(())
}

pub const GEO_KEYS: [u16; 16] = [1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326];

pub fn write_demo(path: &Path, area: &Area) -> Result<()> {
    let grid = Grid::from_area(area, 160, 160);
    let mut samples = Vec::with_capacity(160 * 160 * 4);
    for y in 0..160 {
        for x in 0..160 {
            let red = 0.15;
            let value = -0.15 + 0.95 * f64::from(x) / 159.0 + 0.08 * (f64::from(y) / 15.0).sin();
            let nir = red * (1.0 + value) / (1.0 - value);
            let scl = if (45..70).contains(&x) && (50..100).contains(&y) {
                9.0
            } else {
                4.0
            };
            samples.extend([red as f32, nir as f32, scl, 1.0]);
        }
    }
    let mut encoder = TiffEncoder::new(BufWriter::new(File::create(path)?))?;
    let mut image = encoder.new_image::<colortype::RGBA32Float>(160, 160)?;
    image
        .encoder()
        .write_tag(Tag::ModelPixelScaleTag, &[grid.dx, grid.dy, 0.0][..])?;
    image.encoder().write_tag(
        Tag::ModelTiepointTag,
        &[0.0, 0.0, 0.0, grid.west, grid.north, 0.0][..],
    )?;
    image
        .encoder()
        .write_tag(Tag::GeoKeyDirectoryTag, &GEO_KEYS[..])?;
    image.encoder().write_tag(
        Tag::ImageDescription,
        "SYNTHETIC TEST ONLY; B04,B08,SCL,dataMask; reflectance",
    )?;
    image.write_data(&samples)?;
    Ok(())
}

fn geokeys(epsg: u16) -> Result<Vec<u16>> {
    if epsg == crate::crs::WGS84 || epsg == crate::crs::SIRGAS2000 {
        return Ok(vec![
            1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, epsg,
        ]);
    }
    crate::crs::Transform::new(epsg, crate::crs::WGS84)?;
    Ok(vec![
        1, 1, 0, 4, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, epsg, 3076, 0, 1, 9001,
    ])
}

/// Reproject to an aligned metric SIRGAS/UTM grid. Nearest-neighbour retains
/// measured NDVI values and nodata; source-grid statistics remain authoritative.
pub fn export_sirgas(analysis: &Analysis, area: &Area, resolution: f64) -> Result<Analysis> {
    use geo::{BoundingRect, Coord, MapCoords};
    ensure!(
        resolution.is_finite() && resolution >= 10.0,
        "Resolução UTM mínima: 10 m"
    );
    analysis.grid.validate()?;
    let b = area.bounds;
    let epsg = crate::crs::sirgas_utm((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)?;
    let forward = crate::crs::Transform::new(crate::crs::WGS84, epsg)?;
    let inverse = crate::crs::Transform::new(epsg, crate::crs::WGS84)?;
    let projected = area.polygons.try_map_coords(|c| -> Result<Coord<f64>> {
        let (x, y) = forward.point(c.x, c.y)?;
        Ok(Coord { x, y })
    })?;
    let rect = projected.bounding_rect().context("Área UTM vazia")?;
    // Curved transformed edges may extend beyond transformed vertices. Sample
    // the geographic bounding-box perimeter and leave one pixel of padding.
    let (mut min_x, mut min_y, mut max_x, mut max_y) =
        (rect.min().x, rect.min().y, rect.max().x, rect.max().y);
    for step in 0..=256 {
        let fraction = f64::from(step) / 256.0;
        let lon = b[0] + (b[2] - b[0]) * fraction;
        let lat = b[1] + (b[3] - b[1]) * fraction;
        for (lon, lat) in [(lon, b[1]), (lon, b[3]), (b[0], lat), (b[2], lat)] {
            let (x, y) = forward.point(lon, lat)?;
            min_x = min_x.min(x);
            min_y = min_y.min(y);
            max_x = max_x.max(x);
            max_y = max_y.max(y);
        }
    }
    // Align to a fixed lattice so repeated exports do not drift their pixels.
    let west = ((min_x - resolution) / resolution).floor() * resolution;
    let north = ((max_y + resolution) / resolution).ceil() * resolution;
    let width = ((max_x + resolution - west) / resolution).ceil() as u32;
    let height = ((north - min_y + resolution) / resolution).ceil() as u32;
    ensure!(
        width > 0
            && height > 0
            && width <= 2500
            && height <= 2500
            && u64::from(width) * u64::from(height) <= MAX_PIXELS,
        "Grade UTM excede os limites de processamento"
    );
    let grid = Grid {
        epsg,
        width,
        height,
        west,
        north,
        dx: resolution,
        dy: resolution,
    };
    let source = analysis.grid;
    let mut ndvi = vec![NODATA; (width * height) as usize];
    for row in 0..height {
        for column in 0..width {
            let (x, y) = grid.center(column, row);
            let (lon, lat) = inverse.point(x, y)?;
            if !area.contains(lon, lat) {
                continue;
            }
            let col = ((lon - source.west) / source.dx).floor();
            let line = ((source.north - lat) / source.dy).floor();
            if col >= 0.0
                && col < f64::from(source.width)
                && line >= 0.0
                && line < f64::from(source.height)
            {
                ndvi[(row * width + column) as usize] =
                    analysis.ndvi[(line as u32 * source.width + col as u32) as usize];
            }
        }
    }
    ensure!(
        ndvi.iter().any(|v| *v != NODATA),
        "Grade UTM sem observações válidas"
    );
    Ok(Analysis {
        grid,
        ndvi,
        statistics: analysis.statistics.clone(),
    })
}
