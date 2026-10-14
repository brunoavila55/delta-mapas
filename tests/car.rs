mod support;
use delta_analysis::{area::Area, car};

#[test]
fn imports_nested_car_and_selects_total_without_adding_liquid_or_reserve() {
    let report = car::import(&support::car()).unwrap();
    assert_eq!(report.source_crs, "EPSG:4674");
    assert_eq!(report.target_crs, "EPSG:4326");
    assert_eq!(report.source_features, 2);
    assert_eq!(report.selected_features, 1);
    assert_eq!(report.selected_theme.as_deref(), Some("Área do Imovel"));
    let area = Area::from_json(&report.geometry.to_string()).unwrap();
    assert!((area.bounds[2] - -55.17).abs() < 1e-7);
    assert!(report.area_ha > 105.0 && report.area_ha < 110.0);
    assert_eq!(report.geometry["type"], "MultiPolygon");
    assert!((area.sirgas_area_ha().unwrap() - report.area_ha).abs() < 1e-8);
}

#[test]
fn reads_portuguese_themes_in_windows_1252_and_requires_crs() {
    let bytes = support::layer(
        "Area_do_Imovel",
        &["Área do Imovel", "Área Líquida do Imóvel"],
        Some(support::SIRGAS),
        true,
    );
    assert_eq!(car::import(&bytes).unwrap().selected_features, 1);
    let no_crs = support::layer("Area_do_Imovel", &["Área do Imovel"], None, false);
    assert!(car::import(&no_crs).is_err());
    let bad_crs = support::layer(
        "Area_do_Imovel",
        &["Área do Imovel"],
        Some("not a coordinate system"),
        false,
    );
    assert!(car::import(&bad_crs).is_err());
    let radians = support::SIRGAS.replace("0.017453292519943295", "1");
    assert!(
        car::import(&support::layer(
            "Area_do_Imovel",
            &["Área do Imovel"],
            Some(&radians),
            false
        ))
        .is_err()
    );
    let mislabeled = support::SIRGAS.replace("298.257222101", "300");
    assert!(
        car::import(&support::layer(
            "Area_do_Imovel",
            &["Área do Imovel"],
            Some(&mislabeled),
            false
        ))
        .is_err()
    );
}

#[test]
fn rejects_reserve_only_ambiguous_property_packages_and_unsafe_paths() {
    let reserve = support::layer(
        "Reserva_Legal",
        &["Reserva Legal Proposta"],
        Some(support::SIRGAS),
        false,
    );
    assert!(car::import(&reserve).is_err());
    let one = support::layer(
        "Area_do_Imovel",
        &["Área do Imovel"],
        Some(support::SIRGAS),
        false,
    );
    let multiple = support::zip(&[("first.zip", &one), ("second.zip", &one)]);
    assert!(car::import(&multiple).is_err());
    let bad = support::zip(&[("../escape.shp", b"data")]);
    assert!(car::import(&bad).is_err());
    let generic = support::layer(
        "area",
        &["Reserva Legal Proposta"],
        Some(support::SIRGAS),
        false,
    );
    assert!(car::import(&generic).is_err());
}

#[test]
fn rejects_truncated_shapes_before_allocating_from_bad_counts() {
    let one = support::layer(
        "Area_do_Imovel",
        &["Área do Imovel"],
        Some(support::SIRGAS),
        false,
    );
    let mut archive = zip::ZipArchive::new(std::io::Cursor::new(&one)).unwrap();
    let mut files = Vec::new();
    for i in 0..archive.len() {
        use std::io::Read;
        let mut file = archive.by_index(i).unwrap();
        let name = file.name().unwrap().to_string();
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes).unwrap();
        if name.ends_with(".shp") {
            bytes[148..152].copy_from_slice(&u32::MAX.to_le_bytes());
        }
        files.push((name, bytes));
    }
    let malformed = support::zip(
        &files
            .iter()
            .map(|(n, b)| (n.as_str(), b.as_slice()))
            .collect::<Vec<_>>(),
    );
    assert!(car::import(&malformed).is_err());
    assert!(car::import(&[0; 20]).is_err());
}

#[test]
fn rejects_too_deep_and_over_budget_archives() {
    let mut nested = support::car();
    for _ in 0..3 {
        nested = support::zip(&[("inner.zip", &nested)]);
    }
    assert!(car::import(&nested).is_err());
    let oversized = vec![0; car::MAX_UPLOAD + 1];
    assert!(car::import(&oversized).is_err());
}
