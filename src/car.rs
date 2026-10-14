//! CAR ZIP import. Everything is decoded in memory; no archive path is extracted.
use crate::area::Area;
use anyhow::{Context, Result, bail, ensure};
use geo::{Coord, Geometry, MapCoords, MultiPolygon, Validation, unary_union};
use proj4rs::Proj;
use serde::Serialize;
use serde_json::Value;
use shapefile::dbase::{self, FieldValue};
use std::{
    collections::BTreeMap,
    io::{Cursor, Read},
    path::Path,
};
use unicode_normalization::{UnicodeNormalization, char::is_combining_mark};

pub const MAX_UPLOAD: usize = 10_000_000;
const MAX_EXPANDED: usize = 32_000_000;
const MAX_FILES: usize = 64;

#[derive(Serialize)]
pub struct ImportReport {
    /// RFC 7946 WGS84 for the browser. Canonical cadastro uses SIRGAS below.
    pub geometry: Value,
    pub cadastral_geometry: Value,
    pub cadastral_crs: &'static str,
    pub area_ha: f64,
    pub source_layer: String,
    pub source_crs: String,
    pub target_crs: &'static str,
    pub source_features: usize,
    pub selected_features: usize,
    pub selected_theme: Option<String>,
    pub warnings: Vec<String>,
}

fn normalized(value: &str) -> String {
    value
        .nfd()
        .filter(|c| !is_combining_mark(*c))
        .flat_map(char::to_lowercase)
        .filter(|c| c.is_ascii_alphanumeric())
        .collect()
}

#[derive(Debug)]
struct CrsNode {
    key: String,
    quoted: Vec<String>,
    numbers: Vec<f64>,
    labels: Vec<String>,
    children: Vec<CrsNode>,
}
struct CrsParser;
impl<'a> proj4wkt::parser::Processor<'a> for CrsParser {
    type Err = &'static str;
    type Output = CrsNode;
    fn process<I>(
        &self,
        key: &'a str,
        _depth: usize,
        attrs: I,
    ) -> std::result::Result<CrsNode, Self::Err>
    where
        I: Iterator<Item = proj4wkt::parser::Attribute<'a, CrsNode>>,
    {
        let mut node = CrsNode {
            key: key.to_ascii_uppercase(),
            quoted: Vec::new(),
            numbers: Vec::new(),
            labels: Vec::new(),
            children: Vec::new(),
        };
        for attribute in attrs {
            use proj4wkt::parser::Attribute;
            match attribute {
                Attribute::Quoted(s) => node.quoted.push(s.to_owned()),
                Attribute::Number(s) => node
                    .numbers
                    .push(s.parse().map_err(|_| "Número inválido no PRJ")?),
                Attribute::Label(s) => node.labels.push(s.to_ascii_uppercase()),
                Attribute::Keyword(_, child) => node.children.push(child),
            }
        }
        Ok(node)
    }
}

fn validate_crs(wkt: &str, epsg: &str) -> Result<()> {
    let (mut depth, mut quoted) = (0_usize, false);
    for c in wkt.chars() {
        if c == '"' {
            quoted = !quoted;
        } else if !quoted && c == '[' {
            depth += 1;
            ensure!(depth <= 12, "PRJ complexo demais");
        } else if !quoted && c == ']' {
            depth = depth.checked_sub(1).context("PRJ inválido")?;
        }
    }
    ensure!(depth == 0 && !quoted, "PRJ incompleto");
    let root = proj4wkt::parser::parse(wkt.trim(), &CrsParser)
        .map_err(|_| anyhow::anyhow!("PRJ inválido"))?;
    let child = |key: &str| {
        root.children
            .iter()
            .find(|n| n.key == key)
            .with_context(|| format!("PRJ sem {key}"))
    };
    let datum = child("DATUM")?;
    let spheroid = datum
        .children
        .iter()
        .find(|n| n.key == "SPHEROID")
        .context("PRJ sem elipsoide")?;
    let inverse = if epsg == "EPSG:4674" {
        298.257222101
    } else {
        298.257223563
    };
    ensure!(
        spheroid.numbers.len() == 2
            && (spheroid.numbers[0] - 6378137.0).abs() < 1e-6
            && (spheroid.numbers[1] - inverse).abs() < 1e-7,
        "Elipsoide incompatível com o CRS declarado"
    );
    if let Some(shift) = datum.children.iter().find(|n| n.key == "TOWGS84") {
        ensure!(
            matches!(shift.numbers.len(), 3 | 7)
                && shift
                    .numbers
                    .iter()
                    .all(|n| n.is_finite() && n.abs() < 1e-12),
            "Transformação de datum não suportada"
        );
    }
    ensure!(
        child("PRIMEM")?.numbers.as_slice() == [0.0],
        "Meridiano não suportado"
    );
    let units = child("UNIT")?;
    ensure!(
        units.numbers.len() == 1 && (units.numbers[0] - std::f64::consts::PI / 180.0).abs() < 1e-16,
        "PRJ deve usar graus"
    );
    let axes: Vec<_> = root.children.iter().filter(|n| n.key == "AXIS").collect();
    ensure!(
        axes.is_empty()
            || (axes.len() == 2 && axes[0].labels == ["EAST"] && axes[1].labels == ["NORTH"]),
        "Ordem de eixos não suportada nesta importação"
    );
    if let Some(authority) = root.children.iter().find(|n| n.key == "AUTHORITY") {
        ensure!(
            authority.quoted == ["EPSG", epsg.strip_prefix("EPSG:").unwrap()],
            "Autoridade do CRS inconsistente"
        );
    }
    Ok(())
}

#[derive(Default)]
struct Budget {
    expanded: usize,
    files: usize,
}
fn unpack(
    bytes: &[u8],
    prefix: &str,
    depth: usize,
    budget: &mut Budget,
    files: &mut BTreeMap<String, Vec<u8>>,
) -> Result<()> {
    ensure!(depth <= 2, "O arquivo contém ZIPs aninhados demais");
    let mut archive =
        zip::ZipArchive::new(Cursor::new(bytes)).context("ZIP corrompido ou não compatível")?;
    ensure!(archive.len() <= MAX_FILES, "ZIP contém arquivos demais");
    for index in 0..archive.len() {
        let mut file = archive.by_index(index)?;
        let path = file
            .enclosed_name()
            .context("ZIP contém caminho inseguro")?;
        let relative = path.to_str().context("Nome de arquivo inválido")?;
        ensure!(
            !relative.contains(['\\', ':']) && !file.encrypted() && !file.is_symlink(),
            "ZIP contém entrada não permitida"
        );
        if file.is_dir() {
            continue;
        }
        if let Some(mode) = file.unix_mode() {
            ensure!(
                matches!(mode & 0o170000, 0 | 0o100000),
                "ZIP contém arquivo especial"
            );
        }
        budget.files += 1;
        ensure!(budget.files <= MAX_FILES, "ZIP contém arquivos demais");
        let declared = usize::try_from(file.size())?;
        ensure!(
            declared <= MAX_EXPANDED
                && budget
                    .expanded
                    .checked_add(declared)
                    .is_some_and(|v| v <= MAX_EXPANDED),
            "ZIP descompactado excede 32 MB"
        );
        ensure!(
            file.compressed_size() > 0 || declared == 0,
            "Tamanho comprimido inválido"
        );
        ensure!(
            file.size() <= file.compressed_size().saturating_mul(500).max(1000),
            "Taxa de compressão excessiva"
        );
        budget.expanded += declared;
        let extension = path
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();
        ensure!(
            matches!(
                extension.as_str(),
                "zip"
                    | "shp"
                    | "shx"
                    | "dbf"
                    | "prj"
                    | "fix"
                    | "cpg"
                    | "qix"
                    | "sbn"
                    | "sbx"
                    | "xml"
            ),
            "O ZIP contém um formato não suportado"
        );
        let mut data = Vec::new();
        (&mut file)
            .take(declared as u64 + 1)
            .read_to_end(&mut data)?;
        ensure!(data.len() == declared, "Tamanho descompactado inesperado");
        let key = format!("{prefix}/{relative}").to_ascii_lowercase();
        if extension == "zip" {
            unpack(&data, &key, depth + 1, budget, files)?;
        } else {
            ensure!(
                files.insert(key, data).is_none(),
                "Arquivo duplicado no ZIP"
            );
        }
    }
    Ok(())
}

fn le_u32(data: &[u8], offset: usize) -> Result<usize> {
    let bytes = data
        .get(offset..offset + 4)
        .context("Shapefile incompleto")?;
    Ok(u32::from_le_bytes(bytes.try_into()?) as usize)
}
fn be_u32(data: &[u8], offset: usize) -> Result<usize> {
    let bytes = data
        .get(offset..offset + 4)
        .context("Shapefile incompleto")?;
    Ok(u32::from_be_bytes(bytes.try_into()?) as usize)
}

/// Check counts before parsers allocate from untrusted SHP/SHX/DBF headers.
fn preflight(shp: &[u8], shx: &[u8], dbf: &[u8]) -> Result<usize> {
    ensure!(
        shp.len() >= 100 && shx.len() >= 100 && dbf.len() >= 33,
        "Shapefile incompleto"
    );
    for bytes in [shp, shx] {
        ensure!(
            be_u32(bytes, 0)? == 9994
                && le_u32(bytes, 28)? == 1000
                && be_u32(bytes, 24)?.checked_mul(2) == Some(bytes.len()),
            "Cabeçalho SHP/SHX inválido"
        );
    }
    let kind = le_u32(shp, 32)?;
    ensure!(
        matches!(kind, 5 | 15 | 25) && le_u32(shx, 32)? == kind,
        "A camada deve conter polígonos"
    );
    ensure!((shx.len() - 100).is_multiple_of(8), "Índice SHX inválido");
    let (mut pos, mut records, mut all_points) = (100_usize, 0_usize, 0_usize);
    while pos < shp.len() {
        ensure!(records < 256, "Camada contém feições demais");
        let record_size = be_u32(shp, pos + 4)?
            .checked_mul(2)
            .context("Registro SHP inválido")?;
        let begin = pos + 8;
        let end = begin
            .checked_add(record_size)
            .context("Registro SHP inválido")?;
        ensure!(
            end <= shp.len() && record_size >= 44 && le_u32(shp, begin)? == kind,
            "Registro SHP inválido"
        );
        let parts = le_u32(shp, begin + 36)?;
        let points = le_u32(shp, begin + 40)?;
        ensure!(
            (1..=1000).contains(&parts) && (4..=10_000).contains(&points),
            "Limite de pontos ou componentes excedido"
        );
        all_points += points;
        ensure!(all_points <= 10_000, "Camada excede 10.000 coordenadas");
        ensure!(
            44 + parts * 4 + points * 16 <= record_size,
            "Registro SHP incompleto"
        );
        let coordinates = begin + 44 + parts * 4;
        for part in 0..parts {
            let start = le_u32(shp, begin + 44 + part * 4)?;
            let stop = if part + 1 == parts {
                points
            } else {
                le_u32(shp, begin + 44 + (part + 1) * 4)?
            };
            ensure!(
                (part != 0 || start == 0) && stop <= points && stop >= start + 4,
                "Anel SHP inválido"
            );
            let first = &shp[coordinates + start * 16..coordinates + start * 16 + 16];
            let last = &shp[coordinates + (stop - 1) * 16..coordinates + stop * 16];
            ensure!(first == last, "Anel SHP aberto");
        }
        ensure!(
            be_u32(shx, 100 + records * 8)?.checked_mul(2) == Some(pos)
                && be_u32(shx, 104 + records * 8)?.checked_mul(2) == Some(record_size),
            "Índice SHX diverge do SHP"
        );
        records += 1;
        pos = end;
    }
    ensure!(
        records > 0 && (shx.len() - 100) / 8 == records && le_u32(dbf, 4)? == records,
        "Contagem SHP/SHX/DBF divergente"
    );
    let header = usize::from(u16::from_le_bytes(dbf[8..10].try_into()?));
    let row = usize::from(u16::from_le_bytes(dbf[10..12].try_into()?));
    ensure!(
        header >= 33
            && row > 0
            && header
                .checked_add(records * row)
                .is_some_and(|v| v <= dbf.len()),
        "DBF incompleto"
    );
    for i in 0..records {
        ensure!(
            dbf[header + i * row] == b' ',
            "DBF contém registros removidos; reexporte a camada"
        );
    }
    Ok(records)
}

fn read_records(
    shp: &[u8],
    shx: &[u8],
    dbf: &[u8],
    encoding: dbase::encoding::DynEncoding,
) -> Result<Vec<(MultiPolygon<f64>, Option<String>)>> {
    let shapes = shapefile::ShapeReader::with_shx(Cursor::new(shp), Cursor::new(shx))?;
    let attributes = dbase::ReaderBuilder::new()
        .with_encoding(encoding)
        .build(Cursor::new(dbf))?;
    let mut reader = shapefile::Reader::new(shapes, attributes);
    let mut records = Vec::new();
    for entry in reader.iter_shapes_and_records() {
        let (shape, record) = entry?;
        let theme = record.as_ref().iter().find_map(|(key, value)| {
            if normalized(key) == "tema" {
                match value {
                    FieldValue::Character(Some(s)) => Some(s.trim().to_owned()),
                    _ => None,
                }
            } else {
                None
            }
        });
        let Geometry::MultiPolygon(polygons) = Geometry::<f64>::try_from(shape)? else {
            bail!("A camada deve conter polígonos");
        };
        polygons
            .check_validation()
            .map_err(|_| anyhow::anyhow!("A camada contém geometria inválida"))?;
        records.push((polygons, theme));
    }
    Ok(records)
}

pub fn import(bytes: &[u8]) -> Result<ImportReport> {
    ensure!(
        !bytes.is_empty() && bytes.len() <= MAX_UPLOAD,
        "Envie um ZIP de até 10 MB"
    );
    let mut files = BTreeMap::new();
    unpack(bytes, "", 0, &mut Budget::default(), &mut files)?;
    let layers: Vec<_> = files.keys().filter(|p| p.ends_with(".shp")).collect();
    let boundaries: Vec<_> = layers
        .iter()
        .copied()
        .filter(|p| {
            let stem = Path::new(p)
                .file_stem()
                .and_then(|n| n.to_str())
                .unwrap_or("");
            matches!(normalized(stem).as_str(), "areadoimovel" | "areaimovel")
        })
        .collect();
    let layer = match boundaries.as_slice() {
        [one] => *one,
        [] if layers.len() == 1 => layers[0],
        [] => bail!("Não foi encontrada uma única camada Área do Imóvel; envie o ZIP dessa camada"),
        _ => bail!("Há mais de uma camada Área do Imóvel; envie um único imóvel"),
    };
    let stem = layer.strip_suffix(".shp").unwrap();
    let source_layer = Path::new(stem)
        .file_name()
        .and_then(|p| p.to_str())
        .context("Nome de camada inválido")?
        .to_owned();
    ensure!(
        !matches!(
            normalized(&source_layer).as_str(),
            "reservalegal" | "coberturadosolo" | "app"
        ),
        "Esta camada não representa o limite do imóvel; envie Área do Imóvel"
    );
    let component = |extension: &str| {
        files
            .get(&format!("{stem}.{extension}"))
            .map(Vec::as_slice)
            .with_context(|| format!("Falta o componente .{extension} da camada"))
    };
    let (shp, shx, dbf) = (component("shp")?, component("shx")?, component("dbf")?);
    let source_features = preflight(shp, shx, dbf)?;
    let wkt = std::str::from_utf8(component("prj")?).context("PRJ deve estar em UTF-8")?;
    ensure!(
        wkt.len() <= 8192 && wkt.trim_start().to_ascii_uppercase().starts_with("GEOGCS["),
        "Nesta versão, use CAR geográfico em SIRGAS 2000 ou WGS84"
    );
    let label = normalized(wkt.split('"').nth(1).context("PRJ inválido")?);
    let source_crs = match label.as_str() {
        "sirgas2000" | "gcssirgas2000" => "EPSG:4674",
        "wgs84" | "gcswgs1984" | "wgs1984" => "EPSG:4326",
        _ => bail!("CRS não suportado; use SIRGAS 2000 ou WGS84 geográfico"),
    };
    validate_crs(wkt, source_crs)?;
    let definition = proj4wkt::wkt_to_projstring(wkt).context("PRJ inválido")?;
    let src = Proj::from_proj_string(&definition).context("Não foi possível ler o CRS")?;
    ensure!(src.is_latlong(), "O CRS deve usar longitude e latitude");
    let dst = Proj::from_proj_string("+proj=longlat +datum=WGS84 +no_defs")?;
    let cpg = files.get(&format!("{stem}.cpg"));
    let records = if let Some(cpg) = cpg {
        let label = std::str::from_utf8(cpg)?.trim().as_bytes();
        let encoding = if label == b"65001" {
            encoding_rs::UTF_8
        } else if label == b"1252" {
            encoding_rs::WINDOWS_1252
        } else {
            encoding_rs::Encoding::for_label(label).context("Codificação CPG não suportada")?
        };
        read_records(
            shp,
            shx,
            dbf,
            dbase::encoding::EncodingRs::from(encoding).into(),
        )?
    } else {
        read_records(shp, shx, dbf, dbase::encoding::Unicode.into()).or_else(|_| {
            read_records(
                shp,
                shx,
                dbf,
                dbase::encoding::EncodingRs::from(encoding_rs::WINDOWS_1252).into(),
            )
        })?
    };
    ensure!(
        records.len() == source_features,
        "Contagem de feições inesperada"
    );
    let primary: Vec<_> = records
        .iter()
        .filter(|(_, theme)| {
            theme.as_ref().is_some_and(|t| {
                matches!(
                    normalized(t).as_str(),
                    "areadoimovel" | "areaimovel" | "areatotaldoimovel"
                )
            })
        })
        .collect();
    let selected = if !primary.is_empty() {
        primary
    } else if records.len() == 1 && records[0].1.is_none() {
        records.iter().collect()
    } else {
        bail!("Não foi possível distinguir a área total das demais feições do CAR")
    };
    let selected_features = selected.len();
    let selected_theme = selected.first().and_then(|(_, theme)| theme.clone());
    let combined = unary_union(selected.iter().map(|(polygon, _)| polygon));
    let transformed = combined.try_map_coords(|c| -> Result<Coord<f64>> {
        ensure!(
            c.x.is_finite()
                && c.y.is_finite()
                && (-180.0..=180.0).contains(&c.x)
                && (-90.0..=90.0).contains(&c.y),
            "Coordenadas geográficas inválidas"
        );
        let (lon, lat) = proj4rs::adaptors::transform_vertex_2d(
            &src,
            &dst,
            (c.x.to_radians(), c.y.to_radians()),
        )?;
        Ok(Coord {
            x: lon.to_degrees(),
            y: lat.to_degrees(),
        })
    })?;
    let geometry =
        serde_json::to_value(geojson::Geometry::new(geojson::Value::from(&transformed)))?;
    let area = Area::from_json(&geometry.to_string())?;
    area.grid_size(10.0)?;
    let mut warnings = vec![
        "O CAR delimita o imóvel inteiro; não separa automaticamente os talhões de cultivo.".into(),
    ];
    if source_features > selected_features {
        warnings
            .push("As demais feições cadastrais foram ignoradas para não duplicar a área.".into());
    }
    Ok(ImportReport {
        area_ha: area.sirgas_area_ha()?,
        cadastral_geometry: area.sirgas_geometry()?,
        cadastral_crs: "EPSG:4674",
        geometry,
        source_layer,
        source_crs: source_crs.into(),
        target_crs: "EPSG:4326",
        source_features,
        selected_features,
        selected_theme,
        warnings,
    })
}
