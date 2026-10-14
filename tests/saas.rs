use axum::{
    body::{Body, to_bytes},
    http::{Request, StatusCode},
};
use delta_analysis::saas::{App, Config, tenant_tx, web, worker, worker_tx};
use serde_json::{Value, json};
use tower::ServiceExt;
use uuid::Uuid;
mod support;

struct Reply {
    status: StatusCode,
    value: Value,
    bytes: Vec<u8>,
    cookie: Option<String>,
}
async fn call(
    app: &App,
    method: &str,
    path: &str,
    session: Option<(&str, &str)>,
    body: Value,
    key: Option<&str>,
    origin: bool,
) -> Reply {
    let mut request = Request::builder()
        .method(method)
        .uri(path)
        .header("content-type", "application/json");
    if origin {
        request = request.header("origin", &app.config.origin);
    }
    if let Some((cookie, csrf)) = session {
        request = request.header("cookie", cookie);
        if !csrf.is_empty() {
            request = request.header("x-csrf-token", csrf);
        }
    }
    if let Some(key) = key {
        request = request.header("idempotency-key", key);
    }
    let response = web::router(app.clone())
        .oneshot(
            request
                .body(if method == "GET" {
                    Body::empty()
                } else {
                    Body::from(body.to_string())
                })
                .unwrap(),
        )
        .await
        .unwrap();
    let status = response.status();
    let cookie = response
        .headers()
        .get("set-cookie")
        .map(|h| h.to_str().unwrap().to_owned());
    let bytes = to_bytes(response.into_body(), 80_000_000)
        .await
        .unwrap()
        .to_vec();
    let value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    Reply {
        status,
        value,
        bytes,
        cookie,
    }
}

#[tokio::test]
#[ignore = "requires dedicated TEST_DATABASE_URL with PostGIS and non-superuser role"]
async fn accounts_isolation_queue_and_private_downloads() {
    let temp = tempfile::tempdir().unwrap();
    let app = App::new(Config {
        database_url: std::env::var("TEST_DATABASE_URL").expect("TEST_DATABASE_URL"),
        origin: "http://127.0.0.1:3010".into(),
        bind: "127.0.0.1:3010".into(),
        storage: temp.path().to_owned(),
        secure_cookie: false,
        registration: true,
        demo_enabled: true,
    })
    .await
    .unwrap();
    // Exercise the real upgrade with an existing WGS84 field and queued snapshot.
    let old_migrations = temp.path().join("old-migrations");
    std::fs::create_dir(&old_migrations).unwrap();
    std::fs::write(
        old_migrations.join("0001_accounts.sql"),
        include_str!("../migrations/0001_accounts.sql"),
    )
    .unwrap();
    sqlx::migrate::Migrator::new(old_migrations.as_path())
        .await
        .unwrap()
        .run(&app.pool)
        .await
        .unwrap();
    let legacy_user = Uuid::new_v4();
    let legacy_property = Uuid::new_v4();
    let legacy_field = Uuid::new_v4();
    let legacy_revision = Uuid::new_v4();
    let legacy_job = Uuid::new_v4();
    let original =
        delta_analysis::area::Area::read(std::path::Path::new("examples/talhao.geojson"))
            .unwrap()
            .geometry;
    let mut tx = worker_tx(&app.pool).await.unwrap();
    sqlx::query("INSERT INTO accounts(id,email,password_hash,reserved) VALUES($1,'migration@example.test','unused',1)").bind(legacy_user).execute(&mut *tx).await.unwrap();
    sqlx::query("INSERT INTO properties(id,user_id,name) VALUES($1,$2,'Legacy')")
        .bind(legacy_property)
        .bind(legacy_user)
        .execute(&mut *tx)
        .await
        .unwrap();
    sqlx::query("INSERT INTO fields(id,user_id,property_id,name,revision,geometry,shape,area_ha) VALUES($1,$2,$3,'Legacy',$4,$5,ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON($5::jsonb),4326)),128)")
        .bind(legacy_field).bind(legacy_user).bind(legacy_property).bind(legacy_revision).bind(&original).execute(&mut *tx).await.unwrap();
    sqlx::query("INSERT INTO analyses(id,user_id,field_id,field_revision,geometry,date_from,date_to,max_cloud,origin,mode,idempotency_key,fingerprint) VALUES($1,$2,$3,$4,$5,'2026-09-01','2026-09-30',20,'manual','synthetic','migration','migration')")
        .bind(legacy_job).bind(legacy_user).bind(legacy_field).bind(legacy_revision).bind(&original).execute(&mut *tx).await.unwrap();
    tx.commit().await.unwrap();
    sqlx::migrate!().run(&app.pool).await.unwrap();
    let mut tx = worker_tx(&app.pool).await.unwrap();
    let upgraded: (i32,i32,Uuid,bool,f64) = sqlx::query_as("SELECT ST_SRID(shape),geometry_crs,revision,ST_Equals(shape,ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($2::jsonb),4326),4674))),area_ha FROM fields WHERE id=$1")
        .bind(legacy_field).bind(&original).fetch_one(&mut *tx).await.unwrap();
    assert_eq!(
        (upgraded.0, upgraded.1, upgraded.2, upgraded.3),
        (4674, 4674, legacy_revision, true)
    );
    assert!(upgraded.4 > 120.0 && upgraded.4 < 130.0);
    let snapshot: (i32, Value) =
        sqlx::query_as("SELECT geometry_crs,geometry FROM analyses WHERE id=$1")
            .bind(legacy_job)
            .fetch_one(&mut *tx)
            .await
            .unwrap();
    assert_eq!(snapshot.0, 4674);
    let converted = delta_analysis::area::Area::from_sirgas_json(&snapshot.1.to_string()).unwrap();
    assert!(
        (converted.bounds[0] - original["coordinates"][0][0][0].as_f64().unwrap()).abs() < 1e-9
    );
    sqlx::query("DELETE FROM analyses WHERE id=$1")
        .bind(legacy_job)
        .execute(&mut *tx)
        .await
        .unwrap();
    sqlx::query("DELETE FROM fields WHERE id=$1")
        .bind(legacy_field)
        .execute(&mut *tx)
        .await
        .unwrap();
    sqlx::query("DELETE FROM properties WHERE id=$1")
        .bind(legacy_property)
        .execute(&mut *tx)
        .await
        .unwrap();
    sqlx::query("DELETE FROM accounts WHERE id=$1")
        .bind(legacy_user)
        .execute(&mut *tx)
        .await
        .unwrap();
    tx.commit().await.unwrap();
    let a_email = format!("a-{}@example.com", Uuid::new_v4());
    let b_email = format!("b-{}@example.com", Uuid::new_v4());
    let password = "correct-horse-battery-staple";
    let register_a = call(
        &app,
        "POST",
        "/api/register",
        None,
        json!({"email":a_email,"password":password}),
        None,
        true,
    )
    .await;
    assert_eq!(register_a.status, StatusCode::OK);
    let a_cookie = register_a.cookie.unwrap();
    assert!(a_cookie.contains("HttpOnly") && a_cookie.contains("SameSite=Strict"));
    let a_cookie = a_cookie.split(';').next().unwrap().to_owned();
    let a_csrf = register_a.value["csrf_token"].as_str().unwrap().to_owned();
    let register_b = call(
        &app,
        "POST",
        "/api/register",
        None,
        json!({"email":b_email,"password":password}),
        None,
        true,
    )
    .await;
    let b_cookie = register_b
        .cookie
        .unwrap()
        .split(';')
        .next()
        .unwrap()
        .to_owned();
    let b_csrf = register_b.value["csrf_token"].as_str().unwrap().to_owned();
    let a = Some((a_cookie.as_str(), a_csrf.as_str()));
    let b = Some((b_cookie.as_str(), b_csrf.as_str()));
    // CAR import is authenticated and CSRF-protected, with no raw file persistence.
    let import_request = |session: Option<(&str, &str)>| {
        let mut request = Request::builder()
            .method("POST")
            .uri("/api/imports/car")
            .header("origin", &app.config.origin)
            .header("content-type", "application/zip");
        if let Some((cookie, csrf)) = session {
            request = request
                .header("cookie", cookie)
                .header("x-csrf-token", csrf);
        }
        request.body(Body::from(support::car())).unwrap()
    };
    assert_eq!(
        web::router(app.clone())
            .oneshot(import_request(None))
            .await
            .unwrap()
            .status(),
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        web::router(app.clone())
            .oneshot(import_request(Some((&a_cookie, "bad-token"))))
            .await
            .unwrap()
            .status(),
        StatusCode::FORBIDDEN
    );
    let imported = web::router(app.clone())
        .oneshot(import_request(a))
        .await
        .unwrap();
    assert_eq!(imported.status(), StatusCode::OK);
    let report: Value =
        serde_json::from_slice(&to_bytes(imported.into_body(), 2_000_000).await.unwrap()).unwrap();
    assert_eq!(report["selected_features"], 1);
    assert_eq!(report["source_crs"], "EPSG:4674");
    assert!(!report.to_string().contains("password"));
    // The upload route accepts larger files than the normal 2 MB JSON limit.
    let bytes = support::layer(
        "Area_do_Imovel",
        &["Área do Imovel"],
        Some(support::SIRGAS),
        false,
    );
    let mut archive = zip::ZipArchive::new(std::io::Cursor::new(bytes)).unwrap();
    let mut parts = Vec::new();
    for index in 0..archive.len() {
        use std::io::Read;
        let mut file = archive.by_index(index).unwrap();
        let name = file.name().unwrap().to_string();
        let mut data = Vec::new();
        file.read_to_end(&mut data).unwrap();
        parts.push((name, data));
    }
    parts.push(("Area_do_Imovel.fix".into(), vec![0; 2_500_000]));
    let body = support::zip(
        &parts
            .iter()
            .map(|(n, d)| (n.as_str(), d.as_slice()))
            .collect::<Vec<_>>(),
    );
    let large = Request::builder()
        .method("POST")
        .uri("/api/imports/car")
        .header("content-type", "application/zip")
        .header("origin", &app.config.origin)
        .header("cookie", &a_cookie)
        .header("x-csrf-token", &a_csrf)
        .body(Body::from(body))
        .unwrap();
    assert_eq!(
        web::router(app.clone())
            .oneshot(large)
            .await
            .unwrap()
            .status(),
        StatusCode::OK
    );
    for path in ["/api/me", "/api/fields", "/api/analyses", "/api/properties"] {
        assert_eq!(
            call(&app, "GET", path, None, Value::Null, None, false)
                .await
                .status,
            StatusCode::UNAUTHORIZED
        );
    }
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/properties",
            a,
            json!({"name":"A"}),
            None,
            false
        )
        .await
        .status,
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/properties",
            Some((&a_cookie, "")),
            json!({"name":"A"}),
            None,
            true
        )
        .await
        .status,
        StatusCode::FORBIDDEN
    );
    let pa = call(
        &app,
        "POST",
        "/api/properties",
        a,
        json!({"name":"Propriedade A"}),
        None,
        true,
    )
    .await
    .value["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let pb = call(
        &app,
        "POST",
        "/api/properties",
        b,
        json!({"name":"Propriedade B"}),
        None,
        true,
    )
    .await
    .value["id"]
        .as_str()
        .unwrap()
        .to_owned();
    assert_eq!(
        call(
            &app,
            "GET",
            &format!("/api/properties/{pa}"),
            b,
            Value::Null,
            None,
            false
        )
        .await
        .status,
        StatusCode::NOT_FOUND
    );
    let geo: Value = serde_json::from_str(include_str!("../examples/talhao.geojson")).unwrap();
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/fields",
            b,
            json!({"name":"Ataque","property_id":pa,"geometry":geo}),
            None,
            true
        )
        .await
        .status,
        StatusCode::NOT_FOUND
    );
    let new_field = call(
        &app,
        "POST",
        "/api/fields",
        a,
        json!({"name":"Talhão A","property_id":pa,"geometry":geo}),
        None,
        true,
    )
    .await;
    assert_eq!(new_field.status, StatusCode::CREATED);
    let field_id = new_field.value["id"].as_str().unwrap().to_owned();
    let b_field = call(
        &app,
        "POST",
        "/api/fields",
        b,
        json!({"name":"Talhão B","property_id":pb,"geometry":geo}),
        None,
        true,
    )
    .await
    .value["id"]
        .as_str()
        .unwrap()
        .to_owned();
    assert_eq!(
        call(
            &app,
            "GET",
            &format!("/api/fields/{field_id}"),
            b,
            Value::Null,
            None,
            false
        )
        .await
        .status,
        StatusCode::NOT_FOUND
    );
    assert_eq!(
        call(
            &app,
            "PUT",
            &format!("/api/fields/{field_id}"),
            b,
            json!({"name":"Ataque","property_id":pb,"geometry":geo}),
            None,
            true
        )
        .await
        .status,
        StatusCode::NOT_FOUND
    );
    let requests = json!({"field_id":field_id,"date_from":"2026-09-01","date_to":"2026-09-30","max_cloud":20,"mode":"synthetic"});
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/analyses",
            b,
            requests.clone(),
            Some("foreign-field"),
            true
        )
        .await
        .status,
        StatusCode::NOT_FOUND
    );
    let created = call(
        &app,
        "POST",
        "/api/analyses",
        a,
        requests.clone(),
        Some("first-request"),
        true,
    )
    .await;
    assert_eq!(created.status, StatusCode::CREATED);
    let id = created.value["id"].as_str().unwrap().to_owned();
    let again = call(
        &app,
        "POST",
        "/api/analyses",
        a,
        requests.clone(),
        Some("first-request"),
        true,
    )
    .await;
    assert_eq!(again.status, StatusCode::OK);
    assert_eq!(again.value["id"], id);
    let mut changed = requests.clone();
    changed["max_cloud"] = json!(50);
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/analyses",
            a,
            changed,
            Some("first-request"),
            true
        )
        .await
        .status,
        StatusCode::CONFLICT
    );
    let me = call(&app, "GET", "/api/me", a, Value::Null, None, false)
        .await
        .value;
    assert_eq!(me["usage"]["reserved"], 1);
    assert_eq!(me["usage"]["used"], 0);
    let a_id: Uuid = me["id"].as_str().unwrap().parse().unwrap();
    let me_b = call(&app, "GET", "/api/me", b, Value::Null, None, false)
        .await
        .value;
    let b_id: Uuid = me_b["id"].as_str().unwrap().parse().unwrap();
    // RLS hides A's rows even if a future query accidentally omits owner predicates.
    let mut tx = tenant_tx(&app.pool, b_id).await.unwrap();
    let leaked: i64 = sqlx::query_scalar("SELECT count(*) FROM analyses")
        .fetch_one(&mut *tx)
        .await
        .unwrap();
    assert_eq!(leaked, 0);
    tx.commit().await.unwrap();
    let unscoped: i64 = sqlx::query_scalar("SELECT count(*) FROM properties")
        .fetch_one(&app.pool)
        .await
        .unwrap();
    assert_eq!(unscoped, 0);
    let mut tx = tenant_tx(&app.pool, b_id).await.unwrap();
    assert!(
        sqlx::query("INSERT INTO properties(id,user_id,name) VALUES($1,$2,'intrusion')")
            .bind(Uuid::new_v4())
            .bind(a_id)
            .execute(&mut *tx)
            .await
            .is_err()
    );
    tx.rollback().await.unwrap();
    let mut changed_geo = geo.clone();
    changed_geo["geometry"]["coordinates"][0][1][0] = json!(-47.918);
    assert_eq!(
        call(
            &app,
            "PUT",
            &format!("/api/fields/{field_id}"),
            a,
            json!({"name":"Talhão atualizado","property_id":pa,"geometry":changed_geo}),
            None,
            true
        )
        .await
        .status,
        StatusCode::OK
    );
    let snapshot = call(
        &app,
        "GET",
        &format!("/api/analyses/{id}"),
        a,
        Value::Null,
        None,
        false,
    )
    .await
    .value;
    assert_eq!(snapshot["storage_crs"], "EPSG:4674");
    assert_eq!(snapshot["geometry_crs"], "EPSG:4326");
    let before = delta_analysis::area::Area::from_json(&geo.to_string()).unwrap();
    let after = delta_analysis::area::Area::from_json(&snapshot["geometry"].to_string()).unwrap();
    for (a, b) in before.bounds.iter().zip(after.bounds) {
        assert!((a - b).abs() < 1e-9);
    }
    // Simulate a crashed worker whose lease has expired; the task must be reclaimed.
    let mut tx = worker_tx(&app.pool).await.unwrap();
    sqlx::query("UPDATE analyses SET status='running',attempts=1,lease_token=$1,lease_until=now()-interval '1 second' WHERE id=$2")
        .bind(Uuid::new_v4()).bind(id.parse::<Uuid>().unwrap()).execute(&mut *tx).await.unwrap();
    tx.commit().await.unwrap();
    assert!(worker::once(&app).await.unwrap());
    assert!(!worker::once(&app).await.unwrap());
    let result = call(
        &app,
        "GET",
        &format!("/api/analyses/{id}"),
        a,
        Value::Null,
        None,
        false,
    )
    .await;
    assert_eq!(result.value["status"], "completed");
    assert_eq!(result.value["attempts"], 2);
    let me = call(&app, "GET", "/api/me", a, Value::Null, None, false)
        .await
        .value;
    assert_eq!(me["usage"]["reserved"], 0);
    assert_eq!(me["usage"]["used"], 1);
    for file in ["ndvi.png", "report.pdf", "ndvi.tif", "analysis.json"] {
        let path = format!("/api/analyses/{id}/files/{file}");
        let owned = call(&app, "GET", &path, a, Value::Null, None, false).await;
        assert_eq!(owned.status, StatusCode::OK);
        assert!(!owned.bytes.is_empty());
        assert_eq!(
            call(&app, "GET", &path, b, Value::Null, None, false)
                .await
                .status,
            StatusCode::NOT_FOUND
        );
        assert_eq!(
            call(&app, "GET", &path, None, Value::Null, None, false)
                .await
                .status,
            StatusCode::UNAUTHORIZED
        );
    }
    assert_eq!(
        call(
            &app,
            "GET",
            &format!("/api/analyses/{id}"),
            b,
            Value::Null,
            None,
            false
        )
        .await
        .status,
        StatusCode::NOT_FOUND
    );
    // Terminal failures release the reservation once, without charging the account.
    let failed=call(&app,"POST","/api/analyses",b,json!({"field_id":b_field,"date_from":"2026-09-01","date_to":"2026-09-30","max_cloud":20,"mode":"synthetic"}),Some("failure-case"),true).await;
    let fail_id = failed.value["id"]
        .as_str()
        .unwrap()
        .parse::<Uuid>()
        .unwrap();
    let mut tx = worker_tx(&app.pool).await.unwrap();
    sqlx::query("UPDATE analyses SET status='running',attempts=3,lease_until=now()-interval '1 second' WHERE id=$1").bind(fail_id).execute(&mut *tx).await.unwrap();
    tx.commit().await.unwrap();
    assert!(!worker::once(&app).await.unwrap());
    let me = call(&app, "GET", "/api/me", b, Value::Null, None, false)
        .await
        .value;
    assert_eq!(me["usage"]["reserved"], 0);
    assert_eq!(me["usage"]["used"], 0);
    assert!(!worker::once(&app).await.unwrap());
    // Two simultaneous submissions cannot overrun one available analysis.
    sqlx::query("UPDATE accounts SET analysis_limit=1 WHERE id=$1")
        .bind(b_id)
        .execute(&app.pool)
        .await
        .unwrap();
    let body = json!({"field_id":b_field,"date_from":"2026-09-01","date_to":"2026-09-30","max_cloud":20,"mode":"synthetic"});
    let (one, two) = tokio::join!(
        call(
            &app,
            "POST",
            "/api/analyses",
            b,
            body.clone(),
            Some("race-1"),
            true
        ),
        call(&app, "POST", "/api/analyses", b, body, Some("race-2"), true)
    );
    assert!([one.status, two.status].contains(&StatusCode::CREATED));
    assert!([one.status, two.status].contains(&StatusCode::PAYMENT_REQUIRED));
    assert!(worker::once(&app).await.unwrap());
    let login = call(
        &app,
        "POST",
        "/api/login",
        None,
        json!({"email":a_email.to_uppercase(),"password":password}),
        None,
        true,
    )
    .await;
    assert_eq!(login.status, StatusCode::OK);
    assert_eq!(
        call(&app, "POST", "/api/logout", a, json!({}), None, true)
            .await
            .status,
        StatusCode::OK
    );
    assert_eq!(
        call(&app, "GET", "/api/me", a, Value::Null, None, false)
            .await
            .status,
        StatusCode::UNAUTHORIZED
    );
    let bad_login = call(
        &app,
        "POST",
        "/api/login",
        None,
        json!({"email":a_email,"password":"wrong"}),
        None,
        true,
    )
    .await;
    assert_eq!(bad_login.status, StatusCode::UNAUTHORIZED);
    for _ in 0..5 {
        let _ = call(
            &app,
            "POST",
            "/api/login",
            None,
            json!({"email":a_email,"password":"wrong"}),
            None,
            true,
        )
        .await;
    }
    assert_eq!(
        call(
            &app,
            "POST",
            "/api/login",
            None,
            json!({"email":a_email,"password":"wrong"}),
            None,
            true
        )
        .await
        .status,
        StatusCode::TOO_MANY_REQUESTS
    );
    // Clean our own test accounts and outputs; no other database is touched.
    let mut tx = worker_tx(&app.pool).await.unwrap();
    sqlx::query("DELETE FROM analyses WHERE user_id IN ($1,$2)")
        .bind(a_id)
        .bind(b_id)
        .execute(&mut *tx)
        .await
        .unwrap();
    sqlx::query("DELETE FROM fields WHERE user_id IN ($1,$2)")
        .bind(a_id)
        .bind(b_id)
        .execute(&mut *tx)
        .await
        .unwrap();
    sqlx::query("DELETE FROM properties WHERE user_id IN ($1,$2)")
        .bind(a_id)
        .bind(b_id)
        .execute(&mut *tx)
        .await
        .unwrap();
    sqlx::query("DELETE FROM accounts WHERE id IN ($1,$2)")
        .bind(a_id)
        .bind(b_id)
        .execute(&mut *tx)
        .await
        .unwrap();
    tx.commit().await.unwrap();
}
