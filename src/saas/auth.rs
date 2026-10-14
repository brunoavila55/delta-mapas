use super::{App, web::ApiError};
use anyhow::{Result, ensure};
use argon2::{
    Argon2, PasswordHash, PasswordHasher, PasswordVerifier,
    password_hash::{SaltString, rand_core::OsRng},
};
use axum::{
    Json,
    extract::{Request, State},
    http::{StatusCode, header},
    middleware::Next,
    response::{IntoResponse, Response},
};
use rand::RngCore;
use serde::Deserialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use sqlx::FromRow;
use uuid::Uuid;

pub fn normalize_email(email: &str) -> Result<String> {
    let email = email.trim().to_lowercase();
    let parts: Vec<_> = email.split('@').collect();
    ensure!(
        email.len() <= 254
            && parts.len() == 2
            && !parts[0].is_empty()
            && parts[1].contains('.')
            && !email.chars().any(char::is_whitespace)
            && !parts[1].starts_with('.')
            && !parts[1].ends_with('.'),
        "E-mail inválido"
    );
    Ok(email)
}

pub fn validate_password(password: &str) -> Result<()> {
    ensure!(
        (12..=128).contains(&password.chars().count()) && password.len() <= 512,
        "Senha deve ter entre 12 e 128 caracteres"
    );
    Ok(())
}

pub async fn hash_password(password: &str) -> Result<String> {
    let password = password.to_owned();
    tokio::task::spawn_blocking(move || {
        Argon2::default()
            .hash_password(password.as_bytes(), &SaltString::generate(&mut OsRng))
            .map(|hash| hash.to_string())
            .map_err(|_| anyhow::anyhow!("Falha ao proteger senha"))
    })
    .await?
}

pub fn digest(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}

fn random_token() -> String {
    let mut bytes = [0_u8; 32];
    rand::rngs::OsRng.fill_bytes(&mut bytes);
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

#[derive(Clone, FromRow)]
pub struct User {
    pub id: Uuid,
    pub email: String,
    pub csrf_token: String,
    pub token_hash: String,
}

pub async fn require_user(
    State(app): State<App>,
    mut request: Request,
    next: Next,
) -> Result<Response, ApiError> {
    let cookie = request
        .headers()
        .get(header::COOKIE)
        .and_then(|h| h.to_str().ok())
        .and_then(|cookies| {
            cookies.split(';').find_map(|c| {
                let (name, value) = c.trim().split_once('=')?;
                (name == app.config.cookie_name()).then_some(value)
            })
        })
        .ok_or(ApiError::unauthorized())?;
    if cookie.len() != 64 || !cookie.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(ApiError::unauthorized());
    }
    let user = sqlx::query_as::<_, User>("SELECT a.id,a.email,s.csrf_token,s.token_hash FROM sessions s JOIN accounts a ON a.id=s.user_id WHERE s.token_hash=$1 AND s.expires_at>now()")
        .bind(digest(cookie)).fetch_optional(&app.pool).await?.ok_or(ApiError::unauthorized())?;
    if !request.method().is_safe()
        && request
            .headers()
            .get("x-csrf-token")
            .and_then(|v| v.to_str().ok())
            != Some(&user.csrf_token)
    {
        return Err(ApiError(
            StatusCode::FORBIDDEN,
            "Sessão inválida para esta ação; recarregue a página",
        ));
    }
    request.extensions_mut().insert(user);
    Ok(next.run(request).await)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Credentials {
    pub email: String,
    pub password: String,
}

async fn throttle(app: &App, email: &str) -> Result<(), ApiError> {
    let count: i32 = sqlx::query_scalar("INSERT INTO auth_limits(key_hash,attempts,expires_at) VALUES ($1,1,now()+interval '1 minute') ON CONFLICT(key_hash) DO UPDATE SET attempts=CASE WHEN auth_limits.expires_at<=now() THEN 1 ELSE auth_limits.attempts+1 END, expires_at=CASE WHEN auth_limits.expires_at<=now() THEN now()+interval '1 minute' ELSE auth_limits.expires_at END RETURNING attempts")
        .bind(digest(&format!("account:{email}"))).fetch_one(&app.pool).await?;
    if count > 5 {
        return Err(ApiError(
            StatusCode::TOO_MANY_REQUESTS,
            "Muitas tentativas; tente novamente em um minuto",
        ));
    }
    Ok(())
}

async fn session(app: &App, id: Uuid) -> Result<Response, ApiError> {
    let token = random_token();
    let csrf = random_token();
    sqlx::query("INSERT INTO sessions(token_hash,user_id,csrf_token) VALUES ($1,$2,$3)")
        .bind(digest(&token))
        .bind(id)
        .bind(&csrf)
        .execute(&app.pool)
        .await?;
    let secure = if app.config.secure_cookie {
        "; Secure"
    } else {
        ""
    };
    let cookie = format!(
        "{}={token}; HttpOnly; Path=/; SameSite=Strict; Max-Age=1209600{secure}",
        app.config.cookie_name()
    );
    Ok((
        [(header::SET_COOKIE, cookie)],
        Json(json!({"csrf_token": csrf})),
    )
        .into_response())
}

pub async fn login(
    State(app): State<App>,
    Json(credentials): Json<Credentials>,
) -> Result<Response, ApiError> {
    let email = normalize_email(&credentials.email).map_err(|_| ApiError::unauthorized())?;
    throttle(&app, &email).await?;
    if credentials.password.len() > 512 {
        return Err(ApiError::unauthorized());
    }
    let row: Option<(Uuid, String)> =
        sqlx::query_as("SELECT id,password_hash FROM accounts WHERE email=$1")
            .bind(email)
            .fetch_optional(&app.pool)
            .await?;
    let hash = row
        .as_ref()
        .map(|(_, h)| h.clone())
        .unwrap_or_else(|| (*app.dummy_password_hash).clone());
    let permit = app
        .password_slots
        .clone()
        .acquire_owned()
        .await
        .map_err(|_| ApiError::internal())?;
    let valid = tokio::task::spawn_blocking(move || {
        let _permit = permit;
        PasswordHash::new(&hash).ok().is_some_and(|h| {
            Argon2::default()
                .verify_password(credentials.password.as_bytes(), &h)
                .is_ok()
        })
    })
    .await
    .map_err(|_| ApiError::internal())?;
    let (id, _) = row.filter(|_| valid).ok_or(ApiError::unauthorized())?;
    session(&app, id).await
}

pub async fn register(
    State(app): State<App>,
    Json(credentials): Json<Credentials>,
) -> Result<Response, ApiError> {
    if !app.config.registration {
        return Err(ApiError(
            StatusCode::FORBIDDEN,
            "Cadastro público ainda não está disponível",
        ));
    }
    let email = normalize_email(&credentials.email)
        .map_err(|_| ApiError::bad("Informe um e-mail válido"))?;
    validate_password(&credentials.password)
        .map_err(|_| ApiError::bad("Use uma senha de 12 a 128 caracteres"))?;
    throttle(&app, &email).await?;
    let _permit = app
        .password_slots
        .acquire()
        .await
        .map_err(|_| ApiError::internal())?;
    let hash = hash_password(&credentials.password)
        .await
        .map_err(|_| ApiError::internal())?;
    let id = Uuid::new_v4();
    let inserted = sqlx::query("INSERT INTO accounts(id,email,password_hash) VALUES ($1,$2,$3) ON CONFLICT(email) DO NOTHING")
        .bind(id).bind(email).bind(hash).execute(&app.pool).await?.rows_affected();
    if inserted == 0 {
        return Err(ApiError(
            StatusCode::CONFLICT,
            "Não foi possível criar a conta com este e-mail",
        ));
    }
    session(&app, id).await
}

pub async fn logout(
    State(app): State<App>,
    axum::Extension(user): axum::Extension<User>,
) -> Result<Response, ApiError> {
    sqlx::query("DELETE FROM sessions WHERE token_hash=$1")
        .bind(user.token_hash)
        .execute(&app.pool)
        .await?;
    let secure = if app.config.secure_cookie {
        "; Secure"
    } else {
        ""
    };
    Ok((
        [(
            header::SET_COOKIE,
            format!(
                "{}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0{secure}",
                app.config.cookie_name()
            ),
        )],
        Json(json!({"ok": true})),
    )
        .into_response())
}
