use delta_analysis::{
    area::Area,
    provider,
    raster::{self, Bands, Grid, NODATA},
};
use serde_json::json;
use std::{fs, io::Cursor, process::Command};

fn area_from(value: serde_json::Value, directory: &std::path::Path) -> Area {
    let file = directory.join("area.geojson");
    fs::write(&file, value.to_string()).unwrap();
    Area::read(&file).unwrap()
}

#[test]
fn ndvi_known_values_and_invalid_observations() {
    assert!((raster::pixel_ndvi(0.2, 0.6, 4.0, 1.0).unwrap() - 0.5).abs() < 1e-6);
    assert!((raster::pixel_ndvi(0.6, 0.2, 6.0, 1.0).unwrap() + 0.5).abs() < 1e-6);
    for scl in [0.0, 1.0, 2.0, 3.0, 7.0, 8.0, 9.0, 10.0, 11.0, 4.5] {
        assert!(raster::pixel_ndvi(0.2, 0.6, scl, 1.0).is_none());
    }
    for (red, nir, mask) in [
        (0.0, 0.0, 1.0),
        (-9999.0, 0.6, 1.0),
        (f32::NAN, 0.6, 1.0),
        (0.2, f32::INFINITY, 1.0),
        (0.2, 0.6, 0.0),
        (0.2, 0.6, 2.0),
    ] {
        assert!(raster::pixel_ndvi(red, nir, 4.0, mask).is_none());
    }
}

#[test]
fn holes_are_excluded_from_values_and_coverage_denominator() {
    let dir = tempfile::tempdir().unwrap();
    let area = area_from(
        json!({"type":"Polygon", "coordinates":[
            [[0.0,0.0],[0.01,0.0],[0.01,0.01],[0.0,0.01],[0.0,0.0]],
        [[0.004,0.004],[0.004,0.006],[0.006,0.006],[0.006,0.004],[0.004,0.004]]
        ]}),
        dir.path(),
    );
    let mut samples = [0.2, 0.6, 4.0, 1.0].repeat(25);
    samples[2] = 9.0; // One cloud in the actual area.
    let bands = Bands {
        grid: Grid::from_area(&area, 5, 5),
        samples,
    };
    let result = raster::calculate(&bands, &area).unwrap();
    assert_eq!(result.statistics.pixels_in_area, 24);
    assert_eq!(result.statistics.valid_pixels, 23);
    assert!((result.statistics.mean - 0.5).abs() < 1e-6);
    assert!((result.statistics.valid_percent - 23.0 / 24.0 * 100.0).abs() < 1e-8);
    assert_eq!(result.ndvi[12], NODATA);
    assert_eq!(result.ndvi[0], NODATA);
}

#[test]
fn no_valid_pixels_and_mismatched_bands_are_errors() {
    let dir = tempfile::tempdir().unwrap();
    let area = Area::read(std::path::Path::new("examples/talhao.geojson")).unwrap();
    let bands = Bands {
        grid: Grid::from_area(&area, 10, 10),
        samples: [0.2, 0.6, 9.0, 1.0].repeat(100),
    };
    assert!(raster::calculate(&bands, &area).is_err());
    let file = dir.path().join("invalid.geojson");
    fs::write(
        &file,
        r#"{"type":"Polygon","coordinates":[[[0,0],[0.01,0.01],[0.01,0],[0,0.01],[0,0]]]}"#,
    )
    .unwrap();
    assert!(Area::read(&file).is_err());
    fs::write(
        &file,
        r#"{"type":"Polygon","coordinates":[[[0,0],[0.01,0],[0.01,0.01],[0,0.01]]]}"#,
    )
    .unwrap();
    assert!(Area::read(&file).is_err());
    let bands = Bands {
        samples: vec![0.0; 12],
        ..bands
    };
    assert!(raster::calculate(&bands, &area).is_err());
}

#[test]
fn request_rejects_invalid_dates_clouds_and_large_grids() {
    let area = Area::read(std::path::Path::new("examples/talhao.geojson")).unwrap();
    let from = "2026-01-01".parse().unwrap();
    let to = "2026-01-31".parse().unwrap();
    assert!(provider::request_payload(&area, to, from, 20.0, 10.0).is_err());
    assert!(provider::request_payload(&area, from, to, 101.0, 10.0).is_err());
    assert!(provider::request_payload(&area, from, to, 20.0, 0.0).is_err());
    let request = provider::request_payload(&area, from, to, 20.0, 10.0).unwrap();
    assert_eq!(request["output"]["responses"][1]["identifier"], "userdata");
    assert_eq!(request["input"]["bounds"]["geometry"]["type"], "Polygon");
}

fn archive(files: &[(&str, &[u8])]) -> Vec<u8> {
    let mut builder = tar::Builder::new(Vec::new());
    for (name, data) in files {
        let mut header = tar::Header::new_gnu();
        header.set_size(data.len() as u64);
        header.set_mode(0o600);
        header.set_cksum();
        builder
            .append_data(&mut header, name, Cursor::new(data))
            .unwrap();
    }
    builder.into_inner().unwrap()
}

#[test]
fn provider_requires_actual_scene_provenance() {
    let source = br#"{"tiles":[{"date":"2026-01-01T12:00:00Z","shId":123}]}"#;
    let (raster, metadata) = provider::unpack(&archive(&[
        ("bands.tif", b"raster"),
        ("userdata.json", source),
    ]))
    .unwrap();
    assert_eq!(raster, b"raster");
    assert_eq!(metadata["tiles"][0]["shId"], 123);
    assert!(provider::unpack(&archive(&[("bands.tif", b"raster")])).is_err());
    assert!(
        provider::unpack(&archive(&[
            ("bands.tif", b"raster"),
            ("userdata.json", br#"{"tiles":[]}"#)
        ]))
        .is_err()
    );
    assert!(provider::unpack(&archive(&[("unexpected", b"data")])).is_err());
}

#[test]
fn cli_generates_all_products_and_preserves_existing_result() {
    let dir = tempfile::tempdir().unwrap();
    let output = dir.path().join("demo");
    let run = || {
        Command::new(env!("CARGO_BIN_EXE_delta-analysis"))
            .args(["demo", "--area", "examples/talhao.geojson", "--output"])
            .arg(&output)
            .output()
            .unwrap()
    };
    let first = run();
    assert!(
        first.status.success(),
        "{}",
        String::from_utf8_lossy(&first.stderr)
    );
    for name in [
        "ndvi.tif",
        "ndvi.png",
        "report.pdf",
        "map.pdf",
        "analysis.json",
        "bands.tif",
    ] {
        assert!(fs::metadata(output.join(name)).unwrap().len() > 0);
    }
    let metadata: serde_json::Value =
        serde_json::from_slice(&fs::read(output.join("analysis.json")).unwrap()).unwrap();
    assert_eq!(metadata["source"]["kind"], "synthetic");
    assert!(metadata["statistics"]["valid_percent"].as_f64().unwrap() < 100.0);
    let mut tiff =
        tiff::decoder::Decoder::new(fs::File::open(output.join("ndvi.tif")).unwrap()).unwrap();
    assert_eq!(metadata["crs"], "EPSG:31983");
    assert_eq!(metadata["cadastral_crs"], "EPSG:4674");
    assert_eq!(metadata["processing_crs"], "EPSG:4326");
    assert_eq!(metadata["grid"]["dx"], 10.0);
    assert_eq!(metadata["grid"]["dy"], 10.0);
    assert_eq!(
        tiff.dimensions().unwrap(),
        (
            metadata["grid"]["width"].as_u64().unwrap() as u32,
            metadata["grid"]["height"].as_u64().unwrap() as u32
        )
    );
    let keys = tiff
        .get_tag_u16_vec(tiff::tags::Tag::GeoKeyDirectoryTag)
        .unwrap();
    assert!(keys[4..].as_chunks::<4>().0.contains(&[3072, 0, 1, 31983]));
    assert_eq!(
        tiff.get_tag_ascii_string(tiff::tags::Tag::Unknown(42113))
            .unwrap(),
        "-9999"
    );
    let before = fs::read(output.join("analysis.json")).unwrap();
    assert!(!run().status.success());
    assert_eq!(fs::read(output.join("analysis.json")).unwrap(), before);
}

#[test]
fn failed_request_leaves_no_partial_result() {
    let dir = tempfile::tempdir().unwrap();
    let output = dir.path().join("failed");
    let result = Command::new(env!("CARGO_BIN_EXE_delta-analysis"))
        .args([
            "fetch",
            "--area",
            "examples/talhao.geojson",
            "--from",
            "2026-02-01",
            "--to",
            "2026-01-01",
            "--output",
        ])
        .arg(&output)
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert!(!output.exists());
    assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 0);
}
