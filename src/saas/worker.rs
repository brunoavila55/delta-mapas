use super::{App, Config, worker_tx};
use crate::{area::Area, provider, raster, render};
use anyhow::{Result, ensure};
use chrono::NaiveDate;
use serde_json::{Value, json};
use sqlx::FromRow;
use std::{fs, path::PathBuf, time::Duration};
use uuid::Uuid;

#[derive(Clone, FromRow)]
struct Job {
    id: Uuid,
    user_id: Uuid,
    geometry: Value,
    date_from: NaiveDate,
    date_to: NaiveDate,
    max_cloud: f64,
    mode: String,
    lease_token: Uuid,
    attempts: i32,
}

async fn claim(app: &App) -> Result<Option<Job>> {
    let mut tx = worker_tx(&app.pool).await?;
    let released: Vec<Uuid> = sqlx::query_scalar("UPDATE analyses SET status='failed',error='Processamento interrompido após três tentativas',finished_at=now(),lease_until=NULL WHERE status='running' AND lease_until<now() AND attempts>=3 RETURNING user_id")
        .fetch_all(&mut *tx).await?;
    for user in released {
        sqlx::query("UPDATE accounts SET reserved=reserved-1 WHERE id=$1")
            .bind(user)
            .execute(&mut *tx)
            .await?;
    }
    let job = sqlx::query_as::<_,Job>("WITH candidate AS (SELECT id FROM analyses WHERE ((status='queued' AND available_at<=now()) OR (status='running' AND lease_until<now())) AND attempts<3 ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) UPDATE analyses a SET status='running',attempts=attempts+1,lease_token=$1,lease_until=now()+interval '90 seconds',error=NULL FROM candidate c WHERE a.id=c.id RETURNING a.id,a.user_id,a.geometry,a.date_from,a.date_to,a.max_cloud,a.mode,a.lease_token,a.attempts")
        .bind(Uuid::new_v4()).fetch_optional(&mut *tx).await?;
    tx.commit().await?;
    Ok(job)
}

fn directory(app: &App, job: &Job) -> PathBuf {
    app.config
        .storage
        .join(job.user_id.to_string())
        .join(job.id.to_string())
        .join(job.lease_token.to_string())
}

fn process(app: App, job: Job) -> Result<Value> {
    let final_path = directory(&app, &job);
    let parent = final_path.parent().expect("generated path has parent");
    fs::create_dir_all(parent)?;
    let stage = parent.join(format!(".{}.partial", job.lease_token));
    fs::create_dir(&stage)?;
    let result = (|| {
        let area = Area::from_sirgas_json(&job.geometry.to_string())?;
        let source = if job.mode == "synthetic" {
            ensure!(app.config.demo_enabled, "Demonstração desativada no worker");
            raster::write_demo(&stage.join("bands.tif"), &area)?;
            json!({"kind":"synthetic","description":"Demonstração; não são dados de satélite"})
        } else {
            provider::download(
                &area,
                job.date_from,
                job.date_to,
                job.max_cloud,
                10.0,
                &stage,
            )?
        };
        let bands = raster::read_bands(&stage.join("bands.tif"))?;
        let expected = raster::Grid::from_area(&area, bands.grid.width, bands.grid.height);
        ensure!(
            (bands.grid.west - expected.west).abs() < 1e-8
                && (bands.grid.north - expected.north).abs() < 1e-8
                && (bands.grid.dx - expected.dx).abs() < 1e-8
                && (bands.grid.dy - expected.dy).abs() < 1e-8,
            "Grade inesperada do provedor"
        );
        let analysis = raster::calculate(&bands, &area)?;
        let statistics = serde_json::to_value(&analysis.statistics)?;
        render::write_products(&stage, &analysis, &area, source)?;
        // The raw provider bands are temporary, not a customer-facing product.
        fs::remove_file(stage.join("bands.tif"))?;
        ensure!(!final_path.exists(), "Destino da tentativa já existe");
        fs::rename(&stage, &final_path)?;
        Ok(statistics)
    })();
    if result.is_err() {
        let _ = fs::remove_dir_all(&stage);
    }
    result
}

/// Claims a durable task; immutable output per lease prevents an expired worker
/// from overwriting the result owned by a subsequent attempt.
pub async fn once(app: &App) -> Result<bool> {
    let Some(job) = claim(app).await? else {
        return Ok(false);
    };
    let (worker_app, worker_job) = (app.clone(), job.clone());
    let mut task = tokio::task::spawn_blocking(move || process(worker_app, worker_job));
    let result = loop {
        tokio::select! {
            result = &mut task => break result.map_err(anyhow::Error::from).and_then(|r|r),
            _ = tokio::time::sleep(Duration::from_secs(25)) => {
                let mut tx = worker_tx(&app.pool).await?;
                sqlx::query("UPDATE analyses SET lease_until=now()+interval '90 seconds' WHERE id=$1 AND lease_token=$2 AND status='running'")
                    .bind(job.id).bind(job.lease_token).execute(&mut *tx).await?;
                tx.commit().await?;
            }
        }
    };
    let mut tx = worker_tx(&app.pool).await?;
    match result {
        Ok(statistics) => {
            let changed = sqlx::query("UPDATE analyses SET status='completed',statistics=$1,artifact_attempt=$2,finished_at=now(),lease_until=NULL WHERE id=$3 AND user_id=$4 AND lease_token=$2 AND status='running'")
                .bind(statistics).bind(job.lease_token).bind(job.id).bind(job.user_id).execute(&mut *tx).await?.rows_affected();
            if changed == 1 {
                sqlx::query("UPDATE accounts SET reserved=reserved-1,used=used+1 WHERE id=$1")
                    .bind(job.user_id)
                    .execute(&mut *tx)
                    .await?;
            } else {
                let _ = tokio::fs::remove_dir_all(directory(app, &job)).await;
            }
        }
        Err(error) => {
            eprintln!(
                "Analysis {} attempt {} failed: {error:#}",
                job.id, job.attempts
            );
            let terminal = job.attempts >= 3;
            let changed = sqlx::query("UPDATE analyses SET status=$1,error=$2,available_at=now()+attempts*interval '15 seconds',finished_at=CASE WHEN $3 THEN now() ELSE NULL END,lease_until=NULL WHERE id=$4 AND user_id=$5 AND lease_token=$6 AND status='running'")
                .bind(if terminal { "failed" } else { "queued" })
                .bind(if terminal { "Não foi possível concluir a análise; seu limite foi liberado" } else { "Nova tentativa de processamento" })
                .bind(terminal).bind(job.id).bind(job.user_id).bind(job.lease_token).execute(&mut *tx).await?.rows_affected();
            if terminal && changed == 1 {
                sqlx::query("UPDATE accounts SET reserved=reserved-1 WHERE id=$1")
                    .bind(job.user_id)
                    .execute(&mut *tx)
                    .await?;
            }
        }
    }
    tx.commit().await?;
    Ok(true)
}

pub async fn run() -> Result<()> {
    let app = App::new(Config::from_env()?).await?;
    println!("Worker pronto; concorrência de processamento: 1");
    loop {
        match once(&app).await {
            Ok(true) => {}
            Ok(false) => {
                tokio::select! { _=tokio::time::sleep(Duration::from_secs(2))=>{}, _=tokio::signal::ctrl_c()=>break }
            }
            Err(error) => {
                eprintln!("Worker cycle failed: {error}");
                tokio::time::sleep(Duration::from_secs(5)).await;
            }
        }
    }
    Ok(())
}
