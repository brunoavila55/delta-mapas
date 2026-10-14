use crate::{
    area::Area,
    raster::{Analysis, NODATA},
};
use anyhow::Result;
use flate2::{Compression, write::ZlibEncoder};
use image::{Rgb, RgbImage};
use pdf_writer::{Content, Filter, Finish, Name, Pdf, Rect, Ref, Str};
use serde_json::Value;
use std::{fs, io::Write, path::Path};

pub const COLORS: [[u8; 3]; 7] = [
    [153, 63, 38],
    [210, 120, 54],
    [244, 185, 88],
    [242, 222, 141],
    [177, 209, 120],
    [79, 157, 88],
    [24, 101, 65],
];
const BOUNDS: [f32; 8] = [-1.0, -0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0];

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

fn text(content: &mut Content, x: f32, y: f32, size: f32, value: &str) {
    // Portuguese accents are representable with the base font's WinAnsi encoding.
    let encoded: Vec<u8> = value
        .chars()
        .map(|c| u8::try_from(c as u32).unwrap_or(b'?'))
        .collect();
    content.set_fill_rgb(0.10, 0.17, 0.15);
    content.begin_text();
    content.set_font(Name(b"F1"), size);
    content.next_line(x, y);
    content.show(Str(&encoded));
    content.end_text();
}

pub fn write_pdf(
    path: &Path,
    map: &RgbImage,
    analysis: &Analysis,
    area: &Area,
    source: &Value,
) -> Result<()> {
    let mut pdf = Pdf::new();
    let (catalog, pages, page, font, image, stream) = (
        Ref::new(1),
        Ref::new(2),
        Ref::new(3),
        Ref::new(4),
        Ref::new(5),
        Ref::new(6),
    );
    pdf.catalog(catalog).pages(pages);
    pdf.pages(pages).kids([page]).count(1);
    let mut writer = pdf.page(page);
    writer
        .media_box(Rect::new(0.0, 0.0, 842.0, 595.0))
        .parent(pages)
        .contents(stream);
    let mut resources = writer.resources();
    resources.fonts().pair(Name(b"F1"), font);
    resources.x_objects().pair(Name(b"Map"), image);
    resources.finish();
    writer.finish();
    pdf.type1_font(font)
        .base_font(Name(b"Helvetica"))
        .encoding_predefined(Name(b"WinAnsiEncoding"));
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

    let mut content = Content::new();
    content.set_fill_rgb(0.97, 0.98, 0.96);
    content.rect(0.0, 0.0, 842.0, 595.0).fill_nonzero();
    content.set_fill_rgb(0.08, 0.30, 0.22);
    content.rect(32.0, 529.0, 778.0, 3.0).fill_nonzero();
    text(
        &mut content,
        32.0,
        554.0,
        22.0,
        "DELTA / análise de vegetação",
    );
    text(
        &mut content,
        32.0,
        507.0,
        11.0,
        "NDVI - Índice de Vegetação por Diferença Normalizada",
    );
    let kind = source["kind"].as_str().unwrap_or("local");
    let label = match kind {
        "synthetic" => "DEMONSTRAÇÃO / DADOS SINTÉTICOS",
        "satellite" => "SATÉLITE / SENTINEL-2 L2A",
        _ => "ARQUIVO LOCAL / ORIGEM NÃO VERIFICADA",
    };
    text(&mut content, 555.0, 556.0, 9.0, label);

    let g = analysis.grid;
    let lat = g.north - f64::from(g.height) * g.dy / 2.0;
    let correction = if g.epsg == crate::crs::WGS84 {
        lat.to_radians().cos()
    } else {
        1.0
    };
    let aspect = (f64::from(g.width) * g.dx * correction / (f64::from(g.height) * g.dy)) as f32;
    let w = 475.0_f32.min(350.0 * aspect);
    let h = w / aspect;
    let x = 32.0 + (475.0 - w) / 2.0;
    let y = 132.0 + (350.0 - h) / 2.0;
    content
        .save_state()
        .transform([w, 0.0, 0.0, h, x, y])
        .x_object(Name(b"Map"))
        .restore_state();
    text(&mut content, 492.0, 473.0, 12.0, "N");
    content.set_stroke_rgb(0.1, 0.3, 0.2);
    content.move_to(496.0, 444.0).line_to(496.0, 466.0).stroke();
    content
        .move_to(491.0, 461.0)
        .line_to(496.0, 466.0)
        .line_to(501.0, 461.0)
        .stroke();

    let stats = &analysis.statistics;
    let area_ha = area.sirgas_area_ha()?;
    let metadata = &source["metadata"]["tiles"][0];
    let date = metadata["date"].as_str().unwrap_or("não verificada");
    let date = date.chars().take(24).collect::<String>();
    let clouds = metadata["cloudCoverage"]
        .as_f64()
        .map(|n| format!("{n:.1}%"))
        .unwrap_or_else(|| "não verificada".into());
    let rows = [
        ("ÁREA DO TALHÃO", format!("{area_ha:.2} ha")),
        ("DATA DA CENA", date),
        ("NUVENS NA CENA", clouds),
        (
            "PIXELS VÁLIDOS NO TALHÃO",
            format!("{:.1}% ({})", stats.valid_percent, stats.valid_pixels),
        ),
        ("NDVI MÉDIO", format!("{:.4}", stats.mean)),
        (
            "NDVI MÍNIMO / MÁXIMO",
            format!("{:.4} / {:.4}", stats.minimum, stats.maximum),
        ),
        (
            "MAPA / SIRGAS 2000 UTM",
            format!("EPSG:{} / {:.0} m", g.epsg, g.dx),
        ),
        ("MÁSCARA SCL", "Vegetação, solo e água (4, 5, 6)".into()),
    ];
    for (index, (label, value)) in rows.iter().enumerate() {
        let y = 468.0 - index as f32 * 42.0;
        text(&mut content, 555.0, y, 8.0, label);
        text(&mut content, 555.0, y - 17.0, 12.0, value);
    }
    text(
        &mut content,
        32.0,
        104.0,
        9.0,
        "NDVI / escala fixa de -1 a 1",
    );
    for (i, rgb) in COLORS.iter().enumerate() {
        content.set_fill_rgb(
            f32::from(rgb[0]) / 255.0,
            f32::from(rgb[1]) / 255.0,
            f32::from(rgb[2]) / 255.0,
        );
        content
            .rect(32.0 + i as f32 * 64.0, 79.0, 64.0, 14.0)
            .fill_nonzero();
        text(
            &mut content,
            32.0 + i as f32 * 64.0,
            64.0,
            8.0,
            &format!("{:.1}", BOUNDS[i]),
        );
    }
    text(&mut content, 480.0, 64.0, 8.0, "1.0");
    text(
        &mut content,
        555.0,
        90.0,
        9.0,
        "Cinza: pixel sem observação válida.",
    );
    text(
        &mut content,
        555.0,
        74.0,
        9.0,
        "Estatísticas na grade original do satélite.",
    );
    text(
        &mut content,
        32.0,
        30.0,
        8.0,
        "Prova técnica v0.1 / não constitui diagnóstico agronômico / metadados completos em analysis.json",
    );
    pdf.stream(stream, &content.finish());
    fs::write(path, pdf.finish())?;
    Ok(())
}

pub fn write_products(
    directory: &Path,
    analysis: &Analysis,
    area: &Area,
    source: Value,
) -> Result<()> {
    let export = crate::raster::export_sirgas(analysis, area, 10.0)?;
    let map = map_image(&export, area)?;
    map.save(directory.join("ndvi.png"))?;
    crate::raster::write_ndvi(&directory.join("ndvi.tif"), &export)?;
    write_pdf(&directory.join("report.pdf"), &map, &export, area, &source)?;
    let metadata = serde_json::json!({
        "schema_version": 2, "pipeline_version": "ndvi-v2-sirgas", "index": "NDVI",
        "created_at": chrono::Utc::now(), "source": source,
        "grid": export.grid, "crs": format!("EPSG:{}", export.grid.epsg), "nodata": NODATA,
        "processing_grid": analysis.grid, "processing_crs": "EPSG:4326",
        "statistics_grid": "processing_grid", "resampling": "nearest",
        "geometry": area.geometry, "geometry_crs": "EPSG:4326",
        "cadastral_geometry": area.sirgas_geometry()?, "cadastral_crs": "EPSG:4674", "area_ha": area.sirgas_area_ha()?,
        "statistics": analysis.statistics,
        "mask_policy": {"accepted_scl": [4,5,6], "data_mask": 1, "minimum_band_sum": 1e-6},
        "legend": {"bounds": BOUNDS, "rgb": COLORS},
        "products": ["ndvi.tif", "ndvi.png", "report.pdf"]
    });
    fs::write(
        directory.join("analysis.json"),
        serde_json::to_vec_pretty(&metadata)?,
    )?;
    Ok(())
}
