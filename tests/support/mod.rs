use shapefile::{Point, Polygon, PolygonRing, dbase};
use std::io::{Cursor, Write};
use zip::write::SimpleFileOptions;

pub const SIRGAS: &str = r#"GEOGCS["SIRGAS 2000",DATUM["Sistema_de_Referencia_Geocentrico_para_America_del_Sur_2000",SPHEROID["GRS 1980",6378137.0,298.257222101],TOWGS84[0,0,0,0,0,0,0]],PRIMEM["Greenwich",0],UNIT["degree",0.017453292519943295],AXIS["Longitude",EAST],AXIS["Latitude",NORTH],AUTHORITY["EPSG","4674"]]"#;

pub fn zip(files: &[(&str, &[u8])]) -> Vec<u8> {
    let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
    for (name, data) in files {
        writer
            .start_file(
                *name,
                SimpleFileOptions::default().compression_method(zip::CompressionMethod::Stored),
            )
            .unwrap();
        writer.write_all(data).unwrap();
    }
    writer.finish().unwrap().into_inner()
}

pub fn layer(name: &str, themes: &[&str], prj: Option<&str>, cp1252: bool) -> Vec<u8> {
    let (mut shp, mut shx, mut dbf) = (
        Cursor::new(Vec::new()),
        Cursor::new(Vec::new()),
        Cursor::new(Vec::new()),
    );
    {
        let mut writer = shapefile::ShapeWriter::with_shx(&mut shp, &mut shx);
        for (i, _) in themes.iter().enumerate() {
            // Total boundary is larger than the secondary liquid boundary.
            let east = if i == 0 { -55.17 } else { -55.175 };
            let polygon = Polygon::new(PolygonRing::Outer(vec![
                Point::new(-55.18, -30.34),
                Point::new(-55.18, -30.33),
                Point::new(east, -30.33),
                Point::new(east, -30.34),
                Point::new(-55.18, -30.34),
            ]));
            writer.write_shape(&polygon).unwrap();
        }
        writer.finalize().unwrap();
    }
    {
        let builder = if cp1252 {
            dbase::TableWriterBuilder::with_encoding(dbase::encoding::EncodingRs::from(
                encoding_rs::WINDOWS_1252,
            ))
        } else {
            dbase::TableWriterBuilder::with_encoding(dbase::encoding::Unicode)
        };
        let mut writer = builder
            .add_character_field("tema".try_into().unwrap(), 100)
            .build_with_dest(&mut dbf);
        for theme in themes {
            let mut record = dbase::Record::default();
            record.insert(
                "tema".into(),
                dbase::FieldValue::Character(Some((*theme).into())),
            );
            writer.write_record(&record).unwrap();
        }
        writer.finalize().unwrap();
    }
    let mut files = vec![
        (format!("{name}.shp"), shp.into_inner()),
        (format!("{name}.shx"), shx.into_inner()),
        (format!("{name}.dbf"), dbf.into_inner()),
    ];
    if let Some(prj) = prj {
        files.push((format!("{name}.prj"), prj.as_bytes().to_vec()));
    }
    zip(&files
        .iter()
        .map(|(n, d)| (n.as_str(), d.as_slice()))
        .collect::<Vec<_>>())
}

pub fn car() -> Vec<u8> {
    let boundary = layer(
        "Area_do_Imovel",
        &["Área do Imovel", "Área Líquida do Imóvel"],
        Some(SIRGAS),
        false,
    );
    let reserve = layer(
        "Reserva_Legal",
        &["Reserva Legal Proposta"],
        Some(SIRGAS),
        false,
    );
    zip(&[
        ("Area_do_Imovel.zip", &boundary),
        ("Reserva_Legal.zip", &reserve),
    ])
}
