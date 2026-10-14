//! Print layouts share one cartographic plate; raster products remain georeferenced.
use crate::{
    area::Area,
    raster::{Analysis, NODATA},
    render::{BOUNDS, COLORS},
};
use anyhow::{Context, Result};
use flate2::{Compression, write::ZlibEncoder};
use geo::Centroid;
use image::RgbImage;
use pdf_writer::{Content, Filter, Finish, Name, Pdf, Rect, Ref, Str};
use serde_json::{Value, json};
use std::{fs, io::Write, path::Path};

fn width(value: &str, size: f32) -> f32 {
    let (encoded, _, _) = encoding_rs::WINDOWS_1252.encode(value);
    encoded
        .iter()
        .map(|c| crate::pdf_font_metrics::REGULAR_WIDTHS[c.saturating_sub(32) as usize] / 1000.0)
        .sum::<f32>()
        * size
}

fn embed_font(pdf: &mut Pdf, font: Ref, descriptor: Ref, data: Ref, bold: bool) -> Result<()> {
    use crate::pdf_font_metrics::*;
    let (name, bytes, widths, metrics) = if bold {
        (
            b"LiberationSans-Bold".as_slice(),
            include_bytes!("assets/fonts/LiberationSans-Bold.ttf").as_slice(),
            BOLD_WIDTHS,
            BOLD_METRICS,
        )
    } else {
        (
            b"LiberationSans".as_slice(),
            include_bytes!("assets/fonts/LiberationSans-Regular.ttf").as_slice(),
            REGULAR_WIDTHS,
            REGULAR_METRICS,
        )
    };
    let mut dictionary = pdf.indirect(font).dict();
    dictionary.pair(Name(b"Type"), Name(b"Font"));
    dictionary.pair(Name(b"Subtype"), Name(b"TrueType"));
    dictionary.pair(Name(b"BaseFont"), Name(name));
    dictionary.pair(Name(b"Encoding"), Name(b"WinAnsiEncoding"));
    dictionary.pair(Name(b"FirstChar"), 32);
    dictionary.pair(Name(b"LastChar"), 255);
    dictionary.insert(Name(b"Widths")).array().items(widths);
    dictionary.pair(Name(b"FontDescriptor"), descriptor);
    dictionary.finish();
    pdf.font_descriptor(descriptor)
        .name(Name(name))
        .flags(pdf_writer::types::FontFlags::NON_SYMBOLIC)
        .bbox(Rect::new(metrics[0], metrics[1], metrics[2], metrics[3]))
        .italic_angle(0.0)
        .ascent(metrics[4])
        .descent(metrics[5])
        .cap_height(metrics[6])
        .stem_v(if bold { 120.0 } else { 80.0 })
        .font_file2(data);
    let mut compressor = ZlibEncoder::new(Vec::new(), Compression::default());
    compressor.write_all(bytes)?;
    let compressed = compressor.finish()?;
    let mut stream = pdf.stream(data, &compressed);
    stream.filter(Filter::FlateDecode);
    stream.pair(Name(b"Length1"), bytes.len() as i32);
    stream.finish();
    Ok(())
}

fn fitted(value: &str, size: f32, limit: f32) -> String {
    let clean: String = value
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect();
    if width(&clean, size) <= limit {
        return clean;
    }
    let mut result = String::new();
    for c in clean.chars() {
        if width(&format!("{result}{c}..."), size) > limit {
            break;
        }
        result.push(c);
    }
    result + "..."
}
fn text(c: &mut Content, x: f32, y: f32, size: f32, bold: bool, value: &str) {
    let (encoded, _, _) = encoding_rs::WINDOWS_1252.encode(value);
    c.set_fill_rgb(0.10, 0.20, 0.17);
    c.begin_text()
        .set_font(Name(if bold { b"F2" } else { b"F1" }), size)
        .next_line(x, y)
        .show(Str(&encoded))
        .end_text();
}
fn line(c: &mut Content, x: f32, y: f32, xx: f32, yy: f32) {
    c.move_to(x, y).line_to(xx, yy).stroke();
}
fn paragraph(c: &mut Content, x: f32, mut y: f32, size: f32, limit: f32, value: &str) -> f32 {
    let mut current = String::new();
    for word in value.split_whitespace() {
        let next = if current.is_empty() {
            word.to_owned()
        } else {
            format!("{current} {word}")
        };
        if !current.is_empty() && width(&next, size) > limit {
            text(c, x, y, size, false, &current);
            y -= size * 1.55;
            current = word.to_owned();
        } else {
            current = next;
        }
    }
    if !current.is_empty() {
        text(c, x, y, size, false, &current);
        y -= size * 1.55;
    }
    y
}
fn brand(c: &mut Content, x: f32, y: f32) {
    c.set_stroke_rgb(0.08, 0.30, 0.22).set_line_width(2.0);
    c.move_to(x, y)
        .line_to(x + 12.0, y + 22.0)
        .line_to(x + 24.0, y)
        .close_path()
        .stroke();
    text(c, x + 35.0, y + 7.0, 15.0, true, "DELTA MAPAS");
}
fn badge(c: &mut Content, source: &Value, x: f32, y: f32) {
    let label = match source["kind"].as_str() {
        Some("synthetic") => "DEMONSTRAÇÃO / DADOS SINTÉTICOS",
        Some("satellite") => "SENTINEL-2 L2A / COPERNICUS",
        _ => "ARQUIVO LOCAL / ORIGEM NÃO VERIFICADA",
    };
    text(c, x, y, 8.0, true, label);
}
fn row(c: &mut Content, x: f32, y: f32, label: &str, value: &str, limit: f32) {
    text(c, x, y, 7.0, true, label);
    text(c, x, y - 14.0, 9.0, false, &fitted(value, 9.0, limit));
}
fn scene(source: &Value) -> String {
    source["metadata"]["tiles"][0]["date"]
        .as_str()
        .map(|s| s.chars().take(10).collect())
        .unwrap_or_else(|| "Não disponível".into())
}
fn center(area: &Area) -> Result<(f64, f64)> {
    let p = area.polygons.centroid().context("Área sem centroide")?;
    Ok((p.x(), p.y()))
}
fn nice_step(target: f64) -> f64 {
    let power = 10_f64.powf(target.log10().floor());
    [1.0, 2.0, 5.0, 10.0]
        .into_iter()
        .map(|v| v * power)
        .find(|v| *v >= target)
        .unwrap_or(power * 10.0)
}
fn distance(value: f64) -> String {
    if value >= 1000.0 {
        format!("{:.2} km", value / 1000.0)
    } else {
        format!("{value:.0} m")
    }
}

/// Scale uses projected metres and physical PDF points, independent of raster aspect.
#[derive(Debug)]
pub struct MapLayout {
    pub x: f32,
    pub y: f32,
    pub width: f32,
    pub height: f32,
    pub west: f64,
    pub north: f64,
    pub metres_per_point: f64,
    pub scale_denominator: f64,
}
impl MapLayout {
    pub fn new(analysis: &Analysis) -> Self {
        let g = analysis.grid;
        let gw = f64::from(g.width) * g.dx;
        let gh = f64::from(g.height) * g.dy;
        let metres_per_point = (gw / 450.0).max(gh / 334.0) * 1.12;
        let (width, height) = (500.0, 374.0);
        Self {
            x: 65.0,
            y: 140.0,
            width,
            height,
            west: g.west - (f64::from(width) * metres_per_point - gw) / 2.0,
            north: g.north + (f64::from(height) * metres_per_point - gh) / 2.0,
            metres_per_point,
            scale_denominator: metres_per_point * 72.0 / 0.0254,
        }
    }
    fn point(&self, e: f64, n: f64) -> (f32, f32) {
        (
            self.x + ((e - self.west) / self.metres_per_point) as f32,
            self.y + self.height - ((self.north - n) / self.metres_per_point) as f32,
        )
    }
}

fn plate(analysis: &Analysis, area: &Area, source: &Value) -> Result<Content> {
    let mut c = Content::new();
    c.set_fill_rgb(1.0, 1.0, 1.0)
        .rect(0.0, 0.0, 842.0, 595.0)
        .fill_nonzero();
    brand(&mut c, 32.0, 552.0);
    text(&mut c, 255.0, 558.0, 18.0, true, "MAPA DE VEGETAÇÃO / NDVI");
    let context = &source["report_context"];
    let field = context["field_name"].as_str().unwrap_or("Área analisada");
    let property = context["property_name"]
        .as_str()
        .unwrap_or("Propriedade não informada");
    text(
        &mut c,
        255.0,
        542.0,
        9.0,
        false,
        &fitted(&format!("{property} / {field}"), 9.0, 550.0),
    );
    c.set_stroke_rgb(0.08, 0.30, 0.22).set_line_width(1.2);
    line(&mut c, 32.0, 532.0, 810.0, 532.0);
    let m = MapLayout::new(analysis);
    let g = analysis.grid;
    let (left, top) = m.point(g.west, g.north);
    let image_w = (f64::from(g.width) * g.dx / m.metres_per_point) as f32;
    let image_h = (f64::from(g.height) * g.dy / m.metres_per_point) as f32;
    c.save_state()
        .transform([image_w, 0.0, 0.0, image_h, left, top - image_h])
        .x_object(Name(b"Map"))
        .restore_state();
    // UTM grid with outside labels. Extent and raster share the same projection.
    let step = nice_step(f64::from(m.width) * m.metres_per_point / 4.0);
    c.set_stroke_rgb(0.78, 0.83, 0.80).set_line_width(0.35);
    let mut east = (m.west / step).ceil() * step;
    while east <= m.west + f64::from(m.width) * m.metres_per_point {
        let (x, _) = m.point(east, m.north);
        line(&mut c, x, m.y, x, m.y + m.height);
        let label = format!("{east:.0}");
        text(
            &mut c,
            x - width(&label, 7.0) / 2.0,
            m.y - 13.0,
            7.0,
            false,
            &label,
        );
        text(
            &mut c,
            x - width(&label, 7.0) / 2.0,
            m.y + m.height + 7.0,
            7.0,
            false,
            &label,
        );
        east += step;
    }
    let mut north = ((m.north - f64::from(m.height) * m.metres_per_point) / step).ceil() * step;
    while north <= m.north {
        let (_, y) = m.point(m.west, north);
        line(&mut c, m.x, y, m.x + m.width, y);
        let label = format!("{north:.0}");
        text(
            &mut c,
            m.x - width(&label, 7.0) - 7.0,
            y - 2.0,
            7.0,
            false,
            &label,
        );
        north += step;
    }
    // Vector outlines retain polygon holes and disconnected parts.
    let project = crate::crs::Transform::new(4326, g.epsg)?;
    c.set_stroke_rgb(0.05, 0.22, 0.17).set_line_width(1.1);
    for polygon in &area.polygons.0 {
        for ring in std::iter::once(polygon.exterior()).chain(polygon.interiors()) {
            for (i, p) in ring.0.iter().enumerate() {
                let (e, n) = project.point(p.x, p.y)?;
                let (x, y) = m.point(e, n);
                if i == 0 {
                    c.move_to(x, y);
                } else {
                    c.line_to(x, y);
                }
            }
            c.close_path().stroke();
        }
    }
    c.set_stroke_rgb(0.22, 0.34, 0.29)
        .set_line_width(0.8)
        .rect(m.x, m.y, m.width, m.height)
        .stroke();
    // Geographic north computed in the map projection; grid north is not assumed.
    let (lon, lat) = center(area)?;
    let (e, n) = project.point(lon, lat)?;
    let (ne, nn) = project.point(lon, lat + 0.001)?;
    let norm = (ne - e).hypot(nn - n);
    let (dx, dy) = (
        ((ne - e) / norm * 28.0) as f32,
        ((nn - n) / norm * 28.0) as f32,
    );
    c.set_stroke_rgb(0.08, 0.30, 0.22).set_line_width(1.5);
    line(&mut c, 543.0, 468.0, 543.0 + dx, 468.0 + dy);
    line(
        &mut c,
        543.0 + dx,
        468.0 + dy,
        543.0 + dx - dy * 0.16 - dx * 0.22,
        468.0 + dy + dx * 0.16 - dy * 0.22,
    );
    line(
        &mut c,
        543.0 + dx,
        468.0 + dy,
        543.0 + dx + dy * 0.16 - dx * 0.22,
        468.0 + dy - dx * 0.16 - dy * 0.22,
    );
    text(&mut c, 536.0, 502.0, 10.0, true, "N");
    text(&mut c, 496.0, 456.0, 6.5, false, "Norte geográfico");
    // A 1/2/5 scale bar is expressed in the same projected metres as the grid.
    let bar_m = nice_step(m.metres_per_point * 95.0);
    let bar_w = (bar_m / m.metres_per_point) as f32;
    text(
        &mut c,
        65.0,
        102.0,
        8.0,
        true,
        &format!("Escala 1:{:.0} / A4 a 100%", m.scale_denominator),
    );
    for i in 0..4 {
        let shade = if i % 2 == 0 { 0.12 } else { 1.0 };
        c.set_fill_rgb(shade, shade, shade)
            .set_stroke_rgb(0.12, 0.12, 0.12)
            .set_line_width(0.5)
            .rect(65.0 + i as f32 * bar_w / 4.0, 84.0, bar_w / 4.0, 7.0)
            .fill_nonzero_and_stroke();
    }
    text(&mut c, 65.0, 72.0, 7.0, false, "0");
    text(
        &mut c,
        65.0 + bar_w / 2.0 - 8.0,
        72.0,
        7.0,
        false,
        &distance(bar_m / 2.0),
    );
    text(
        &mut c,
        65.0 + bar_w - 12.0,
        72.0,
        7.0,
        false,
        &distance(bar_m),
    );
    text(
        &mut c,
        65.0,
        57.0,
        7.0,
        false,
        "Coordenadas da quadrícula em metros (E / N).",
    );
    badge(&mut c, source, 595.0, 510.0);
    row(
        &mut c,
        595.0,
        483.0,
        "ÁREA CADASTRADA",
        &format!("{:.2} ha", area.sirgas_area_ha()?),
        210.0,
    );
    row(&mut c, 595.0, 448.0, "DATA DA CENA", &scene(source), 210.0);
    let zone = if g.epsg >= 31978 {
        g.epsg - 31960
    } else {
        g.epsg - 31954
    };
    row(
        &mut c,
        595.0,
        413.0,
        "REFERENCIAL CARTOGRÁFICO",
        &format!(
            "SIRGAS 2000 / UTM {zone}{}",
            if lat < 0.0 { "S" } else { "N" }
        ),
        210.0,
    );
    text(
        &mut c,
        595.0,
        386.0,
        8.0,
        false,
        &format!("EPSG:{} / pixel {:.0} m", g.epsg, g.dx),
    );
    row(
        &mut c,
        595.0,
        361.0,
        "CENTROIDE / SIRGAS 2000",
        &format!("Lat {lat:.6}° / Lon {lon:.6}°"),
        210.0,
    );
    text(
        &mut c,
        595.0,
        334.0,
        8.0,
        false,
        &format!("E {e:.1} m / N {n:.1} m"),
    );
    row(
        &mut c,
        595.0,
        309.0,
        "COBERTURA VÁLIDA NO TALHÃO",
        &format!(
            "{:.1}% / NDVI médio {:.3}",
            analysis.statistics.valid_percent, analysis.statistics.mean
        ),
        210.0,
    );
    text(&mut c, 595.0, 265.0, 9.0, true, "LEGENDA / NDVI");
    for (i, color) in COLORS.iter().enumerate() {
        let y = 242.0 - i as f32 * 18.0;
        c.set_fill_rgb(
            color[0] as f32 / 255.0,
            color[1] as f32 / 255.0,
            color[2] as f32 / 255.0,
        )
        .rect(595.0, y - 2.0, 18.0, 10.0)
        .fill_nonzero();
        text(
            &mut c,
            622.0,
            y,
            8.0,
            false,
            &format!("{:.1} a {:.1}", BOUNDS[i], BOUNDS[i + 1]),
        );
    }
    c.set_fill_rgb(204.0 / 255.0, 210.0 / 255.0, 210.0 / 255.0)
        .rect(595.0, 107.0, 18.0, 10.0)
        .fill_nonzero();
    text(&mut c, 622.0, 109.0, 8.0, false, "Sem observação válida");
    paragraph(
        &mut c,
        595.0,
        85.0,
        7.0,
        210.0,
        "Contorno: área cadastrada. Estatísticas na grade original; mapa reamostrado por vizinho mais próximo.",
    );
    text(
        &mut c,
        32.0,
        29.0,
        7.0,
        false,
        "Elaboração: Delta Mapas / NDVI = (B08 - B04) / (B08 + B04) / não constitui diagnóstico agronômico.",
    );
    text(
        &mut c,
        32.0,
        17.0,
        7.0,
        false,
        &format!(
            "Emissão UTC: {} / coordenadas geográficas em graus decimais.",
            source["generated_at"].as_str().unwrap_or("não informada")
        ),
    );
    Ok(c)
}

pub fn distribution(analysis: &Analysis) -> [u64; 7] {
    let mut counts = [0; 7];
    for &value in &analysis.ndvi {
        if value != NODATA && value.is_finite() {
            let bucket = (0..7).find(|&i| value < BOUNDS[i + 1]).unwrap_or(6);
            counts[bucket] += 1;
        }
    }
    counts
}
fn summary(analysis: &Analysis, area: &Area, source: &Value, counts: &[u64; 7]) -> Result<Content> {
    let mut c = Content::new();
    brand(&mut c, 38.0, 786.0);
    badge(&mut c, source, 285.0, 795.0);
    text(&mut c, 38.0, 751.0, 22.0, true, "Relatório de vegetação");
    text(
        &mut c,
        38.0,
        730.0,
        10.0,
        false,
        "Caracterização da área e leitura descritiva do NDVI",
    );
    c.set_stroke_rgb(0.08, 0.30, 0.22).set_line_width(1.0);
    line(&mut c, 38.0, 714.0, 557.0, 714.0);
    let context = &source["report_context"];
    text(
        &mut c,
        38.0,
        692.0,
        12.0,
        true,
        "01 / Identificação e localização",
    );
    row(
        &mut c,
        38.0,
        671.0,
        "PROPRIEDADE",
        context["property_name"].as_str().unwrap_or("Não informada"),
        245.0,
    );
    row(
        &mut c,
        305.0,
        671.0,
        "TALHÃO",
        context["field_name"].as_str().unwrap_or("Área analisada"),
        252.0,
    );
    let (lon, lat) = center(area)?;
    let info = format!(
        "A área cadastrada possui {:.2} ha e {} parte(s) poligonal(is). Seu centroide está em latitude {lat:.6}° e longitude {lon:.6}°. A extensão geográfica vai de {:.6}° a {:.6}° de longitude e de {:.6}° a {:.6}° de latitude. O centroide é uma referência geométrica e pode ficar fora do polígono.",
        area.sirgas_area_ha()?,
        area.polygons.0.len(),
        area.bounds[0],
        area.bounds[2],
        area.bounds[1],
        area.bounds[3]
    );
    paragraph(&mut c, 38.0, 627.0, 9.0, 510.0, &info);
    let culture = context["crop"].as_str().unwrap_or("Não informada");
    let stage = match context["stage"].as_str() {
        Some("vegetative") => "Vegetativa",
        Some("reproductive") => "Reprodutiva",
        Some("maturation") => "Maturação",
        Some("harvest") => "Colheita",
        _ => "Não informada",
    };
    text(
        &mut c,
        38.0,
        548.0,
        9.0,
        false,
        &fitted(
            &format!("Cultura: {culture} / Fase informada: {stage}"),
            9.0,
            510.0,
        ),
    );
    text(
        &mut c,
        38.0,
        516.0,
        12.0,
        true,
        "02 / Observação e qualidade dos dados",
    );
    let stats = &analysis.statistics;
    let clouds = source["metadata"]["tiles"][0]["cloudCoverage"]
        .as_f64()
        .map(|v| format!("{v:.1}%"))
        .unwrap_or_else(|| "Não disponível".into());
    row(&mut c, 38.0, 493.0, "DATA DA CENA", &scene(source), 155.0);
    row(&mut c, 211.0, 493.0, "NUVENS NA CENA", &clouds, 155.0);
    row(
        &mut c,
        384.0,
        493.0,
        "COBERTURA VÁLIDA",
        &format!("{:.1}%", stats.valid_percent),
        170.0,
    );
    let quality = if source["kind"] == "synthetic" {
        "Este documento usa dados sintéticos de demonstração e não descreve as condições reais da vegetação."
    } else if stats.valid_percent < 90.0 {
        "A cobertura válida é inferior a 90%. A leitura representa somente os pixels observados e exige cautela ao comparar datas ou generalizar para toda a área."
    } else {
        "A cobertura válida é de pelo menos 90%. Nuvens da cena e cobertura válida do talhão são medidas distintas; regiões cinza não possuem observação utilizável."
    };
    paragraph(&mut c, 38.0, 454.0, 9.0, 510.0, quality);
    text(
        &mut c,
        38.0,
        398.0,
        12.0,
        true,
        "03 / Distribuição e leitura do índice",
    );
    text(
        &mut c,
        38.0,
        376.0,
        10.0,
        true,
        &format!(
            "Média {:.3} / Mínimo {:.3} / Máximo {:.3}",
            stats.mean, stats.minimum, stats.maximum
        ),
    );
    text(&mut c, 38.0, 352.0, 8.0, true, "FAIXA DE NDVI");
    text(&mut c, 227.0, 352.0, 8.0, true, "PIXELS VÁLIDOS");
    text(&mut c, 401.0, 352.0, 8.0, true, "% DOS PIXELS VÁLIDOS");
    let total = counts.iter().sum::<u64>();
    for (i, count) in counts.iter().enumerate() {
        let y = 332.0 - i as f32 * 18.0;
        let rgb = COLORS[i];
        c.set_fill_rgb(
            rgb[0] as f32 / 255.0,
            rgb[1] as f32 / 255.0,
            rgb[2] as f32 / 255.0,
        )
        .rect(38.0, y - 2.0, 14.0, 9.0)
        .fill_nonzero();
        text(
            &mut c,
            61.0,
            y,
            9.0,
            false,
            &format!("{:.1} a {:.1}", BOUNDS[i], BOUNDS[i + 1]),
        );
        text(&mut c, 227.0, y, 9.0, false, &count.to_string());
        text(
            &mut c,
            401.0,
            y,
            9.0,
            false,
            &format!("{:.1}%", *count as f64 * 100.0 / total.max(1) as f64),
        );
    }
    let dominant = counts
        .iter()
        .enumerate()
        .max_by_key(|(_, n)| *n)
        .map(|(i, _)| i)
        .unwrap_or(0);
    paragraph(
        &mut c,
        38.0,
        203.0,
        9.0,
        510.0,
        &format!(
            "A faixa predominante entre os pixels válidos é {:.1} a {:.1}. Valores maiores representam maior resposta relativa da vegetação neste índice. Valores baixos podem ocorrer em solo exposto, água ou diferentes fases da cultura; isoladamente, não identificam a causa de uma alteração.",
            BOUNDS[dominant],
            BOUNDS[dominant + 1]
        ),
    );
    text(&mut c, 38.0, 127.0, 12.0, true, "04 / Uso do resultado");
    paragraph(
        &mut c,
        38.0,
        107.0,
        8.5,
        510.0,
        "Use o mapa da página seguinte para orientar a inspeção da área e confrontar a distribuição observada com o histórico e a fase da safra. O resultado não estima produtividade, fertilidade, clima ou doenças. A distribuição foi calculada na grade original, sobre pixels válidos, sem extrapolação de área.",
    );
    text(
        &mut c,
        38.0,
        34.0,
        7.0,
        false,
        &format!(
            "Delta Mapas / Emissão UTC: {} / 1 de 2",
            source["generated_at"].as_str().unwrap_or("não informada")
        ),
    );
    Ok(c)
}
fn document(path: &Path, map: &RgbImage, contents: Vec<(f32, f32, Content)>) -> Result<()> {
    let mut pdf = Pdf::new();
    let (catalog, pages, font, bold, image) = (
        Ref::new(1),
        Ref::new(2),
        Ref::new(3),
        Ref::new(4),
        Ref::new(5),
    );
    let refs: Vec<Ref> = (0..contents.len())
        .map(|i| Ref::new(6 + i as i32 * 2))
        .collect();
    pdf.catalog(catalog).pages(pages);
    pdf.pages(pages)
        .kids(refs.iter().copied())
        .count(refs.len() as i32);
    embed_font(&mut pdf, font, Ref::new(100), Ref::new(101), false)?;
    embed_font(&mut pdf, bold, Ref::new(102), Ref::new(103), true)?;
    let mut compressor = ZlibEncoder::new(Vec::new(), Compression::default());
    compressor.write_all(map.as_raw())?;
    let compressed = compressor.finish()?;
    let mut img = pdf.image_xobject(image, &compressed);
    img.filter(Filter::FlateDecode);
    img.width(map.width() as i32)
        .height(map.height() as i32)
        .bits_per_component(8);
    img.color_space().device_rgb();
    img.finish();
    for (index, (w, h, c)) in contents.into_iter().enumerate() {
        let page = refs[index];
        let stream = Ref::new(page.get() + 1);
        let mut p = pdf.page(page);
        p.media_box(Rect::new(0.0, 0.0, w, h))
            .parent(pages)
            .contents(stream);
        let mut resources = p.resources();
        resources
            .fonts()
            .pair(Name(b"F1"), font)
            .pair(Name(b"F2"), bold);
        resources.x_objects().pair(Name(b"Map"), image);
        resources.finish();
        p.finish();
        pdf.stream(stream, &c.finish());
    }
    fs::write(path, pdf.finish())?;
    Ok(())
}

pub fn write_documents(
    directory: &Path,
    map: &RgbImage,
    export: &Analysis,
    original: &Analysis,
    area: &Area,
    source: &Value,
) -> Result<Value> {
    let counts = distribution(original);
    document(
        &directory.join("map.pdf"),
        map,
        vec![(842.0, 595.0, plate(export, area, source)?)],
    )?;
    let mut report_map = plate(export, area, source)?;
    text(&mut report_map, 765.0, 17.0, 7.0, false, "2 de 2");
    document(
        &directory.join("report.pdf"),
        map,
        vec![
            (595.0, 842.0, summary(original, area, source, &counts)?),
            (842.0, 595.0, report_map),
        ],
    )?;
    Ok(json!({"bounds":BOUNDS,"valid_pixel_counts":counts,"grid":"processing_grid"}))
}
