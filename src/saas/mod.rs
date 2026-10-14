pub mod auth;
pub mod web;
pub mod worker;

use anyhow::{Context, Result, ensure};
use sqlx::{PgPool, Postgres, Transaction, postgres::PgPoolOptions};
use std::{env, path::PathBuf, sync::Arc};
use uuid::Uuid;

#[derive(Clone)]
pub struct Config {
    pub database_url: String,
    pub origin: String,
    pub bind: String,
    pub storage: PathBuf,
    pub secure_cookie: bool,
    pub registration: bool,
    pub demo_enabled: bool,
}

impl Config {
    pub fn from_env() -> Result<Self> {
        let origin = env::var("APP_ORIGIN").unwrap_or_else(|_| "https://localhost".into());
        let secure_cookie = env::var("COOKIE_SECURE").unwrap_or_else(|_| "true".into()) == "true";
        let parsed = reqwest::Url::parse(&origin).context("APP_ORIGIN inválida")?;
        ensure!(
            parsed.origin().ascii_serialization() == origin
                && matches!(parsed.scheme(), "http" | "https"),
            "APP_ORIGIN deve conter somente esquema, hostname e porta, sem barra final"
        );
        if !secure_cookie {
            ensure!(
                matches!(parsed.host_str(), Some("localhost" | "127.0.0.1" | "[::1]")),
                "Cookies sem Secure só são permitidos em localhost"
            );
        } else {
            ensure!(
                parsed.scheme() == "https",
                "COOKIE_SECURE requer APP_ORIGIN HTTPS"
            );
        }
        Ok(Self {
            database_url: env::var("DATABASE_URL").context("Configure DATABASE_URL")?,
            origin,
            bind: env::var("APP_BIND").unwrap_or_else(|_| "127.0.0.1:3010".into()),
            storage: env::var("STORAGE_DIRECTORY")
                .map(PathBuf::from)
                .unwrap_or_else(|_| PathBuf::from("output/private")),
            secure_cookie,
            registration: env::var("REGISTRATION_ENABLED").is_ok_and(|v| v == "true"),
            demo_enabled: env::var("DEMO_ENABLED").is_ok_and(|v| v == "true"),
        })
    }

    pub fn cookie_name(&self) -> &'static str {
        if self.secure_cookie {
            "__Host-delta_session"
        } else {
            "delta_session"
        }
    }
}

#[derive(Clone)]
pub struct App {
    pub pool: PgPool,
    pub config: Arc<Config>,
    pub dummy_password_hash: Arc<String>,
    pub password_slots: Arc<tokio::sync::Semaphore>,
    pub import_slots: Arc<tokio::sync::Semaphore>,
}

pub async fn connect(config: &Config) -> Result<PgPool> {
    let pool = PgPoolOptions::new()
        .max_connections(8)
        .connect(&config.database_url)
        .await?;
    let bypass: bool = sqlx::query_scalar(
        "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user",
    )
    .fetch_one(&pool)
    .await?;
    ensure!(
        !bypass,
        "O aplicativo exige um usuário PostgreSQL sem SUPERUSER e sem BYPASSRLS"
    );
    Ok(pool)
}

impl App {
    pub async fn new(config: Config) -> Result<Self> {
        let pool = connect(&config).await?;
        tokio::fs::create_dir_all(&config.storage).await?;
        let dummy_password_hash = auth::hash_password("not-a-real-user-password").await?;
        Ok(Self {
            pool,
            config: Arc::new(config),
            dummy_password_hash: Arc::new(dummy_password_hash),
            password_slots: Arc::new(tokio::sync::Semaphore::new(2)),
            import_slots: Arc::new(tokio::sync::Semaphore::new(2)),
        })
    }
}

pub async fn tenant_tx(
    pool: &PgPool,
    user_id: Uuid,
) -> Result<Transaction<'_, Postgres>, sqlx::Error> {
    let mut tx = pool.begin().await?;
    sqlx::query("SELECT set_config('delta.user_id', $1, true)")
        .bind(user_id.to_string())
        .execute(&mut *tx)
        .await?;
    Ok(tx)
}

pub async fn worker_tx(pool: &PgPool) -> Result<Transaction<'_, Postgres>, sqlx::Error> {
    let mut tx = pool.begin().await?;
    sqlx::query("SELECT set_config('delta.worker', 'on', true)")
        .execute(&mut *tx)
        .await?;
    Ok(tx)
}

pub async fn migrate() -> Result<()> {
    let config = Config::from_env()?;
    let pool = connect(&config).await?;
    sqlx::migrate!().run(&pool).await?;
    println!("Migrations aplicadas.");
    Ok(())
}

pub async fn serve() -> Result<()> {
    let app = App::new(Config::from_env()?).await?;
    let listener = tokio::net::TcpListener::bind(&app.config.bind).await?;
    let cleanup_pool = app.pool.clone();
    tokio::spawn(async move {
        loop {
            let _ = sqlx::query("DELETE FROM sessions WHERE expires_at<=now()")
                .execute(&cleanup_pool)
                .await;
            let _ = sqlx::query("DELETE FROM auth_limits WHERE expires_at<now()-interval '1 day'")
                .execute(&cleanup_pool)
                .await;
            tokio::time::sleep(std::time::Duration::from_secs(600)).await;
        }
    });
    println!("Servidor pronto em {}", app.config.origin);
    axum::serve(
        listener,
        web::router(app).into_make_service_with_connect_info::<std::net::SocketAddr>(),
    )
    .with_graceful_shutdown(async {
        let _ = tokio::signal::ctrl_c().await;
    })
    .await?;
    Ok(())
}

pub async fn provision(email: String) -> Result<()> {
    let config = Config::from_env()?;
    let pool = connect(&config).await?;
    let email = auth::normalize_email(&email)?;
    let password = env::var("DELTA_INITIAL_PASSWORD")
        .context("Configure DELTA_INITIAL_PASSWORD somente para criar a conta")?;
    auth::validate_password(&password)?;
    let hash = auth::hash_password(&password).await?;
    let inserted = sqlx::query("INSERT INTO accounts(id,email,password_hash) VALUES ($1,$2,$3) ON CONFLICT(email) DO NOTHING")
        .bind(Uuid::new_v4()).bind(email).bind(hash).execute(&pool).await?.rows_affected();
    println!(
        "{}",
        if inserted == 1 {
            "Conta criada."
        } else {
            "Conta existente; senha preservada."
        }
    );
    Ok(())
}
