use delta_analysis::{
    area::Area,
    crs,
    raster::{self, Bands, Grid, NODATA},
};
use serde_json::json;

#[test]
fn sirgas_utm_matches_independent_proj_reference_in_both_hemispheres() {
    // Reference coordinates from PROJ/pyproj, always_xy, metres.
    for (lon, lat, epsg, x, y) in [
        (
            -47.925,
            -15.815,
            31983,
            186646.63307343575,
            8249346.903495797,
        ),
        (-55.176, -30.34, 31981, 675332.4114087869, 6642128.881376181),
        (-51.05, 0.04, 31976, 494436.25248599704, 4421.203546332077),
    ] {
        assert_eq!(crs::sirgas_utm(lon, lat).unwrap(), epsg);
        let point = crs::Transform::new(4326, epsg)
            .unwrap()
            .point(lon, lat)
            .unwrap();
        assert!((point.0 - x).abs() < 0.001 && (point.1 - y).abs() < 0.001);
        let restored = crs::Transform::new(epsg, 4326)
            .unwrap()
            .point(point.0, point.1)
            .unwrap();
        assert!((restored.0 - lon).abs() < 1e-9 && (restored.1 - lat).abs() < 1e-9);
    }
    assert!(crs::sirgas_utm(0.0, 0.0).is_err());
    assert!(crs::Transform::new(3857, 4674).is_err());
}

#[test]
fn projected_exports_preserve_holes_nodata_and_observed_values() {
    let area = Area::from_json(&json!({"type":"Polygon","coordinates":[
        [[-55.18,-30.34],[-55.17,-30.34],[-55.17,-30.33],[-55.18,-30.33],[-55.18,-30.34]],
        [[-55.177,-30.337],[-55.177,-30.333],[-55.173,-30.333],[-55.173,-30.337],[-55.177,-30.337]]
    ]}).to_string()).unwrap();
    let mut samples = [0.2, 0.6, 4.0, 1.0].repeat(10000);
    for row in 0..100 {
        for column in 0..20 {
            samples[(row * 100 + column) * 4 + 2] = 9.0;
        }
    }
    let result = raster::calculate(
        &Bands {
            grid: Grid::from_area(&area, 100, 100),
            samples,
        },
        &area,
    )
    .unwrap();
    let export = raster::export_sirgas(&result, &area, 10.0).unwrap();
    assert_eq!(export.grid.epsg, 31981);
    assert_eq!((export.grid.dx, export.grid.dy), (10.0, 10.0));
    let inverse = crs::Transform::new(31981, 4326).unwrap();
    let (mut valid, mut empty, mut outside) = (0, 0, 0);
    for row in 0..export.grid.height {
        for column in 0..export.grid.width {
            let (x, y) = export.grid.center(column, row);
            let (lon, lat) = inverse.point(x, y).unwrap();
            let value = export.ndvi[(row * export.grid.width + column) as usize];
            if !area.contains(lon, lat) {
                outside += 1;
                assert_eq!(value, NODATA);
            }
            if value == NODATA {
                empty += 1;
            } else {
                valid += 1;
                assert!((value - 0.5).abs() < 1e-6);
            }
        }
    }
    assert!(valid > 0 && empty > 0 && outside > 0);
    let canonical = area.sirgas_geometry().unwrap();
    let restored = Area::from_sirgas_json(&canonical.to_string()).unwrap();
    assert!(!restored.contains(-55.175, -30.335));
    assert!((restored.sirgas_area_ha().unwrap() - area.sirgas_area_ha().unwrap()).abs() < 1e-7);
    assert!(raster::export_sirgas(&result, &area, 0.0).is_err());
}
