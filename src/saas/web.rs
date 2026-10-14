use super::{
    App,
    auth::{self, User},
    tenant_tx,
};
use crate::area::Area;
use axum::{
    Extension, Json, Router,
    extract::{DefaultBodyLimit, Path, Request, State},
    http::{HeaderMap, StatusCode, header},
    middleware::{self, Next},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
};
use chrono::NaiveDate;
use serde::Deserialize;
use serde_json::{Value, json};
use uuid::Uuid;

pub struct ApiError(pub StatusCode, pub &'static str);
impl ApiError {
    pub fn bad(message: &'static str) -> Self {
        Self(StatusCode::BAD_REQUEST, message)
    }
    pub fn internal() -> Self {
        Self(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Não foi possível concluir a operação",
        )
    }
    pub fn unauthorized() -> Self {
        Self(
            StatusCode::UNAUTHORIZED,
            "E-mail, senha ou sessão inválidos",
        )
    }
    pub fn missing() -> Self {
        Self(StatusCode::NOT_FOUND, "Item não encontrado")
    }
}
impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.0, Json(json!({"error": self.1}))).into_response()
    }
}
impl From<sqlx::Error> for ApiError {
    fn from(error: sqlx::Error) -> Self {
        eprintln!("Database operation failed: {error}");
        Self::internal()
    }
}

pub fn router(app: App) -> Router {
    let protected = Router::new()
        .route("/api/me", get(me))
        .route("/api/logout", post(auth::logout))
        .route("/api/properties", get(properties).post(create_property))
        .route("/api/properties/{id}", get(property))
        .route("/api/fields", get(fields).post(create_field))
        .route("/api/fields/{id}", get(field).put(update_field))
        .route(
            "/api/imports/car",
            post(import_car).layer(DefaultBodyLimit::max(crate::car::MAX_UPLOAD)),
        )
        .route("/api/analyses", get(analyses).post(create_analysis))
        .route("/api/analyses/{id}", get(analysis))
        .route("/api/analyses/{id}/files/{name}", get(download))
        .route_layer(middleware::from_fn_with_state(
            app.clone(),
            auth::require_user,
        ));
    Router::new()
        .merge(protected)
        .route(
            "/",
            get(|| async { Html(include_str!("../ui/index.html")) }),
        )
        .route(
            "/app.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/javascript; charset=utf-8")],
                    include_str!("../ui/app.js"),
                )
            }),
        )
        .route(
            "/app.css",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/css; charset=utf-8")],
                    include_str!("../ui/app.css"),
                )
            }),
        )
        .route(
            "/health/live",
            get(|| async { Json(json!({"status":"ok"})) }),
        )
        .route("/health/ready", get(ready))
        .route("/api/config", get(config))
        .route("/api/login", post(auth::login))
        .route("/api/register", post(auth::register))
        .layer(DefaultBodyLimit::max(2_100_000))
        .layer(middleware::from_fn_with_state(app.clone(), security))
        .with_state(app)
}

async fn security(State(app): State<App>, request: Request, next: Next) -> Response {
    if !request.method().is_safe()
        && request
            .headers()
            .get(header::ORIGIN)
            .and_then(|v| v.to_str().ok())
            != Some(&app.config.origin)
    {
        return ApiError(StatusCode::FORBIDDEN, "Origem da solicitação não permitida")
            .into_response();
    }
    if request.method() == axum::http::Method::POST
        && matches!(request.uri().path(), "/api/login" | "/api/register")
    {
        let ip = request
            .extensions()
            .get::<axum::extract::ConnectInfo<std::net::SocketAddr>>()
            .map(|v| v.0.ip().to_string())
            .unwrap_or_else(|| "internal-test".into());
        let count = sqlx::query_scalar::<_,i32>("INSERT INTO auth_limits(key_hash,attempts,expires_at) VALUES($1,1,now()+interval '1 minute') ON CONFLICT(key_hash) DO UPDATE SET attempts=CASE WHEN auth_limits.expires_at<=now() THEN 1 ELSE auth_limits.attempts+1 END,expires_at=CASE WHEN auth_limits.expires_at<=now() THEN now()+interval '1 minute' ELSE auth_limits.expires_at END RETURNING attempts")
            .bind(auth::digest(&format!("peer:{ip}"))).fetch_one(&app.pool).await;
        match count {
            Ok(n) if n > 60 => {
                return ApiError(
                    StatusCode::TOO_MANY_REQUESTS,
                    "Muitas tentativas de acesso; aguarde um minuto",
                )
                .into_response();
            }
            Err(error) => return ApiError::from(error).into_response(),
            _ => {}
        }
    }
    let mut response = next.run(request).await;
    let headers = response.headers_mut();
    headers.insert(header::CACHE_CONTROL, "no-store".parse().unwrap());
    headers.insert("x-content-type-options", "nosniff".parse().unwrap());
    headers.insert("referrer-policy", "no-referrer".parse().unwrap());
    headers.insert("content-security-policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'".parse().unwrap());
    response
}

async fn ready(State(app): State<App>) -> Result<Json<Value>, ApiError> {
    sqlx::query("SELECT 1 FROM accounts LIMIT 1")
        .execute(&app.pool)
        .await?;
    Ok(Json(json!({"status":"ok"})))
}
async fn config(State(app): State<App>) -> Json<Value> {
    Json(
        json!({"registration_enabled":app.config.registration, "demo_enabled":app.config.demo_enabled}),
    )
}
async fn me(
    State(app): State<App>,
    Extension(user): Extension<User>,
) -> Result<Json<Value>, ApiError> {
    let account: Value = sqlx::query_scalar("SELECT jsonb_build_object('limit',analysis_limit,'used',used,'reserved',reserved,'available',analysis_limit-used-reserved) FROM accounts WHERE id=$1")
        .bind(user.id).fetch_one(&app.pool).await?;
    Ok(Json(
        json!({"id":user.id,"email":user.email,"csrf_token":user.csrf_token,"usage":account}),
    ))
}

async fn import_car(
    State(app): State<App>,
    Extension(_user): Extension<User>,
    bytes: axum::body::Bytes,
) -> Result<Json<crate::car::ImportReport>, ApiError> {
    let permit = app.import_slots.clone().try_acquire_owned().map_err(|_| {
        ApiError(
            StatusCode::TOO_MANY_REQUESTS,
            "Há importações em andamento; tente novamente em instantes",
        )
    })?;
    let report=tokio::task::spawn_blocking(move || { let _permit=permit; crate::car::import(&bytes) })
        .await.map_err(|_|ApiError::internal())?.map_err(|error| {
            eprintln!("CAR import rejected: {error:#}");
            ApiError::bad("Não foi possível importar. Envie um ZIP CAR com Área do Imóvel, SHP/SHX/DBF/PRJ, em SIRGAS 2000 ou WGS84 geográfico; máximo 10 MB")
        })?;
    Ok(Json(report))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PropertyInput {
    name: String,
}
fn name(value: &str) -> Result<String, ApiError> {
    let value = value.trim();
    if value.is_empty() || value.chars().count() > 120 {
        return Err(ApiError::bad("Nome deve ter de 1 a 120 caracteres"));
    }
    Ok(value.to_owned())
}
async fn create_property(
    State(app): State<App>,
    Extension(user): Extension<User>,
    Json(input): Json<PropertyInput>,
) -> Result<impl IntoResponse, ApiError> {
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    let id = Uuid::new_v4();
    sqlx::query("INSERT INTO properties(id,user_id,name) VALUES ($1,$2,$3)")
        .bind(id)
        .bind(user.id)
        .bind(name(&input.name)?)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok((StatusCode::CREATED, Json(json!({"id":id}))))
}
async fn properties(
    State(app): State<App>,
    Extension(user): Extension<User>,
) -> Result<Json<Value>, ApiError> {
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    let items: Vec<Value> = sqlx::query_scalar("SELECT jsonb_build_object('id',id,'name',name) FROM properties WHERE user_id=$1 ORDER BY created_at DESC LIMIT 100")
        .bind(user.id).fetch_all(&mut *tx).await?;
    Ok(Json(json!(items)))
}
async fn property(
    State(app): State<App>,
    Extension(user): Extension<User>,
    Path(id): Path<Uuid>,
) -> Result<Json<Value>, ApiError> {
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    let item: Option<Value> = sqlx::query_scalar(
        "SELECT jsonb_build_object('id',id,'name',name) FROM properties WHERE id=$1 AND user_id=$2",
    )
    .bind(id)
    .bind(user.id)
    .fetch_optional(&mut *tx)
    .await?;
    Ok(Json(item.ok_or(ApiError::missing())?))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FieldInput {
    name: String,
    property_id: Uuid,
    geometry: Value,
}
async fn persist_field(
    app: App,
    user: User,
    input: FieldInput,
    existing: Option<Uuid>,
) -> Result<(StatusCode, Json<Value>), ApiError> {
    let name = name(&input.name)?;
    let area = Area::from_json(&input.geometry.to_string())
        .map_err(|_| ApiError::bad("Área inválida; importe Polygon ou MultiPolygon em WGS84"))?;
    crate::crs::sirgas_utm(
        (area.bounds[0] + area.bounds[2]) / 2.0,
        (area.bounds[1] + area.bounds[3]) / 2.0,
    )
    .map_err(|_| ApiError::bad("Área fora dos fusos brasileiros suportados para SIRGAS/UTM"))?;
    area.grid_size(10.0)
        .map_err(|_| ApiError::bad("Área excede o tamanho permitido para processamento"))?;
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    let owned: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM properties WHERE id=$1 AND user_id=$2)")
            .bind(input.property_id)
            .bind(user.id)
            .fetch_one(&mut *tx)
            .await?;
    if !owned {
        return Err(ApiError::missing());
    }
    let id = existing.unwrap_or_else(Uuid::new_v4);
    let geometry = area.geometry;
    if existing.is_some() {
        let changed = sqlx::query("UPDATE fields SET name=$1,property_id=$2,geometry=ST_AsGeoJSON(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($3::jsonb),4326),4674),15,0)::jsonb,shape=ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($4),4326),4674)),area_ha=ST_Area(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($4),4326),4674)::geography)/10000.0,revision=$5 WHERE id=$6 AND user_id=$7")
            .bind(name).bind(input.property_id).bind(&geometry).bind(geometry.to_string()).bind(Uuid::new_v4()).bind(id).bind(user.id).execute(&mut *tx).await?.rows_affected();
        if changed == 0 {
            return Err(ApiError::missing());
        }
    } else {
        sqlx::query("INSERT INTO fields(id,user_id,property_id,name,revision,geometry,shape,area_ha) VALUES($1,$2,$3,$4,$5,ST_AsGeoJSON(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($6::jsonb),4326),4674),15,0)::jsonb,ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($7),4326),4674)),ST_Area(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON($7),4326),4674)::geography)/10000.0)")
            .bind(id).bind(user.id).bind(input.property_id).bind(name).bind(Uuid::new_v4()).bind(&geometry).bind(geometry.to_string()).execute(&mut *tx).await?;
    }
    tx.commit().await?;
    Ok((
        if existing.is_some() {
            StatusCode::OK
        } else {
            StatusCode::CREATED
        },
        Json(json!({"id":id})),
    ))
}
async fn create_field(
    State(app): State<App>,
    Extension(user): Extension<User>,
    Json(input): Json<FieldInput>,
) -> Result<impl IntoResponse, ApiError> {
    persist_field(app, user, input, None).await
}
async fn update_field(
    State(app): State<App>,
    Extension(user): Extension<User>,
    Path(id): Path<Uuid>,
    Json(input): Json<FieldInput>,
) -> Result<impl IntoResponse, ApiError> {
    persist_field(app, user, input, Some(id)).await
}
async fn fields(
    State(app): State<App>,
    Extension(user): Extension<User>,
) -> Result<Json<Value>, ApiError> {
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    let items: Vec<Value> = sqlx::query_scalar("SELECT jsonb_build_object('id',f.id,'name',f.name,'property_id',f.property_id,'property_name',p.name,'revision',f.revision,'geometry',ST_AsGeoJSON(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(f.geometry),4674),4326),15,0)::jsonb,'storage_crs','EPSG:4674','geometry_crs','EPSG:4326','area_ha',f.area_ha) FROM fields f JOIN properties p ON p.id=f.property_id AND p.user_id=f.user_id WHERE f.user_id=$1 ORDER BY f.created_at DESC LIMIT 100")
        .bind(user.id).fetch_all(&mut *tx).await?;
    Ok(Json(json!(items)))
}
async fn field(
    State(app): State<App>,
    Extension(user): Extension<User>,
    Path(id): Path<Uuid>,
) -> Result<Json<Value>, ApiError> {
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    let item: Option<Value> = sqlx::query_scalar("SELECT jsonb_build_object('id',id,'name',name,'property_id',property_id,'revision',revision,'geometry',ST_AsGeoJSON(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(geometry),4674),4326),15,0)::jsonb,'storage_crs','EPSG:4674','geometry_crs','EPSG:4326','area_ha',area_ha) FROM fields WHERE id=$1 AND user_id=$2")
        .bind(id).bind(user.id).fetch_optional(&mut *tx).await?;
    Ok(Json(item.ok_or(ApiError::missing())?))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AnalysisInput {
    field_id: Uuid,
    date_from: NaiveDate,
    date_to: NaiveDate,
    max_cloud: f64,
    mode: String,
}
async fn create_analysis(
    State(app): State<App>,
    Extension(user): Extension<User>,
    headers: HeaderMap,
    Json(input): Json<AnalysisInput>,
) -> Result<impl IntoResponse, ApiError> {
    if input.date_from > input.date_to
        || input.date_to > chrono::Utc::now().date_naive()
        || !input.max_cloud.is_finite()
        || !(0.0..=100.0).contains(&input.max_cloud)
    {
        return Err(ApiError::bad("Revise as datas e o limite de nuvens"));
    }
    if input.mode != "satellite" && !(input.mode == "synthetic" && app.config.demo_enabled) {
        return Err(ApiError::bad("Modo de processamento não disponível"));
    }
    let key = headers
        .get("idempotency-key")
        .and_then(|h| h.to_str().ok())
        .filter(|v| !v.is_empty() && v.len() <= 100)
        .ok_or(ApiError::bad(
            "Informe Idempotency-Key de até 100 caracteres",
        ))?;
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    let available: i32 = sqlx::query_scalar(
        "SELECT analysis_limit-used-reserved FROM accounts WHERE id=$1 FOR UPDATE",
    )
    .bind(user.id)
    .fetch_one(&mut *tx)
    .await?;
    let field: Option<(Uuid, Value)> =
        sqlx::query_as("SELECT revision,geometry FROM fields WHERE id=$1 AND user_id=$2")
            .bind(input.field_id)
            .bind(user.id)
            .fetch_optional(&mut *tx)
            .await?;
    let (revision, geometry) = field.ok_or(ApiError::missing())?;
    let fingerprint = auth::digest(
        &json!([
            input.field_id,
            revision,
            input.date_from,
            input.date_to,
            input.max_cloud,
            input.mode,
            "ndvi-v1"
        ])
        .to_string(),
    );
    let old: Option<(Uuid, String)> = sqlx::query_as(
        "SELECT id,fingerprint FROM analyses WHERE user_id=$1 AND idempotency_key=$2",
    )
    .bind(user.id)
    .bind(key)
    .fetch_optional(&mut *tx)
    .await?;
    if let Some((id, existing)) = old {
        if existing != fingerprint {
            return Err(ApiError(
                StatusCode::CONFLICT,
                "Esta chave já foi usada para outra solicitação",
            ));
        }
        return Ok((StatusCode::OK, Json(json!({"id":id,"reused":true}))));
    }
    if available <= 0 {
        return Err(ApiError(
            StatusCode::PAYMENT_REQUIRED,
            "Limite de análises atingido",
        ));
    }
    let id = Uuid::new_v4();
    sqlx::query("INSERT INTO analyses(id,user_id,field_id,field_revision,geometry,date_from,date_to,max_cloud,origin,mode,idempotency_key,fingerprint) VALUES($1,$2,$3,$4,$5,$6,$7,$8,'manual',$9,$10,$11)")
        .bind(id).bind(user.id).bind(input.field_id).bind(revision).bind(geometry).bind(input.date_from).bind(input.date_to).bind(input.max_cloud).bind(input.mode).bind(key).bind(fingerprint).execute(&mut *tx).await?;
    sqlx::query("UPDATE accounts SET reserved=reserved+1 WHERE id=$1")
        .bind(user.id)
        .execute(&mut *tx)
        .await?;
    tx.commit().await?;
    Ok((StatusCode::CREATED, Json(json!({"id":id,"reused":false}))))
}
async fn analyses(
    State(app): State<App>,
    Extension(user): Extension<User>,
) -> Result<Json<Value>, ApiError> {
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    let items: Vec<Value> = sqlx::query_scalar("SELECT jsonb_build_object('id',a.id,'field_name',f.name,'status',a.status,'mode',a.mode,'origin',a.origin,'date_from',a.date_from,'date_to',a.date_to,'created_at',a.created_at,'statistics',a.statistics,'error',a.error) FROM analyses a JOIN fields f ON f.id=a.field_id AND f.user_id=a.user_id WHERE a.user_id=$1 ORDER BY a.created_at DESC LIMIT 100")
        .bind(user.id).fetch_all(&mut *tx).await?;
    Ok(Json(json!(items)))
}
async fn analysis(
    State(app): State<App>,
    Extension(user): Extension<User>,
    Path(id): Path<Uuid>,
) -> Result<Json<Value>, ApiError> {
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    let item: Option<Value> = sqlx::query_scalar("SELECT jsonb_build_object('id',id,'status',status,'mode',mode,'origin',origin,'field_revision',field_revision,'statistics',statistics,'error',error,'attempts',attempts,'geometry',ST_AsGeoJSON(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(geometry),4674),4326),15,0)::jsonb,'storage_crs','EPSG:4674','geometry_crs','EPSG:4326') FROM analyses WHERE id=$1 AND user_id=$2")
        .bind(id).bind(user.id).fetch_optional(&mut *tx).await?;
    Ok(Json(item.ok_or(ApiError::missing())?))
}
async fn download(
    State(app): State<App>,
    Extension(user): Extension<User>,
    Path((id, name)): Path<(Uuid, String)>,
) -> Result<Response, ApiError> {
    let content_type = match name.as_str() {
        "ndvi.png" => "image/png",
        "report.pdf" => "application/pdf",
        "ndvi.tif" => "image/tiff",
        "analysis.json" => "application/json",
        _ => return Err(ApiError::missing()),
    };
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    let attempt: Option<Uuid> = sqlx::query_scalar(
        "SELECT artifact_attempt FROM analyses WHERE id=$1 AND user_id=$2 AND status='completed'",
    )
    .bind(id)
    .bind(user.id)
    .fetch_optional(&mut *tx)
    .await?
    .flatten();
    let attempt = attempt.ok_or(ApiError::missing())?;
    let root = tokio::fs::canonicalize(&app.config.storage)
        .await
        .map_err(|_| ApiError::internal())?;
    let path = root
        .join(user.id.to_string())
        .join(id.to_string())
        .join(attempt.to_string())
        .join(&name);
    let real = tokio::fs::canonicalize(path)
        .await
        .map_err(|_| ApiError::missing())?;
    if !real.starts_with(&root) {
        return Err(ApiError::missing());
    }
    let size = tokio::fs::metadata(&real)
        .await
        .map_err(|_| ApiError::missing())?
        .len();
    if size > 80_000_000 {
        return Err(ApiError::internal());
    }
    let data = tokio::fs::read(real)
        .await
        .map_err(|_| ApiError::missing())?;
    let disposition = if name == "ndvi.png" {
        "inline"
    } else {
        "attachment"
    };
    Ok((
        [
            (header::CONTENT_TYPE, content_type.to_owned()),
            (
                header::CONTENT_DISPOSITION,
                format!("{disposition}; filename=\"{name}\""),
            ),
        ],
        data,
    )
        .into_response())
}
