use super::{App, auth::User, tenant_tx, web::ApiError, worker_tx};
use axum::{
    Extension, Json,
    extract::{Path, State},
};
use chrono::{NaiveDate, Utc};
use serde::Deserialize;
use serde_json::{Value, json};
use sqlx::{FromRow, Postgres, Transaction};
use uuid::Uuid;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    enabled: bool,
    crop: String,
    stage: String,
    season_start: NaiveDate,
    season_end: NaiveDate,
    drop_threshold: f64,
}

pub async fn list(
    State(app): State<App>,
    Extension(user): Extension<User>,
) -> Result<Json<Value>, ApiError> {
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    let rows: Vec<Value> = sqlx::query_scalar(
        "SELECT to_jsonb(m) FROM monitoring m WHERE user_id=$1 ORDER BY field_id",
    )
    .bind(user.id)
    .fetch_all(&mut *tx)
    .await?;
    Ok(Json(json!(rows)))
}

pub async fn save(
    State(app): State<App>,
    Extension(user): Extension<User>,
    Path(field): Path<Uuid>,
    Json(input): Json<Input>,
) -> Result<Json<Value>, ApiError> {
    let crop = input.crop.trim();
    if !matches!(
        input.stage.as_str(),
        "vegetative" | "reproductive" | "maturation" | "harvest"
    ) || crop.is_empty()
        || crop.chars().count() > 80
        || input.season_end < input.season_start
        || (input.season_end - input.season_start).num_days() > 730
        || (input.enabled && input.season_end < Utc::now().date_naive())
        || !input.drop_threshold.is_finite()
        || !(0.05..=1.0).contains(&input.drop_threshold)
    {
        return Err(ApiError::bad(
            "Revise a cultura, o período da safra e o limite de queda (0,05 a 1,00)",
        ));
    }
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    // Serialize configuration changes with field edits.
    let owned: Option<Uuid> =
        sqlx::query_scalar("SELECT id FROM fields WHERE id=$1 AND user_id=$2 FOR UPDATE")
            .bind(field)
            .bind(user.id)
            .fetch_optional(&mut *tx)
            .await?;
    if owned.is_none() {
        return Err(ApiError::missing());
    }
    sqlx::query("INSERT INTO monitoring(user_id,field_id,enabled,generation,crop,season_start,season_end,drop_threshold,stage) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT(field_id) DO UPDATE SET enabled=excluded.enabled,generation=excluded.generation,crop=excluded.crop,stage=excluded.stage,season_start=excluded.season_start,season_end=excluded.season_end,drop_threshold=excluded.drop_threshold,next_run=now(),state='scheduled'")
        .bind(user.id).bind(field).bind(input.enabled).bind(Uuid::new_v4()).bind(crop).bind(input.season_start).bind(input.season_end).bind(input.drop_threshold).bind(input.stage).execute(&mut *tx).await?;
    tx.commit().await?;
    Ok(Json(json!({"saved":true})))
}

pub async fn alerts(
    State(app): State<App>,
    Extension(user): Extension<User>,
) -> Result<Json<Value>, ApiError> {
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    let rows: Vec<Value>=sqlx::query_scalar("SELECT to_jsonb(a) || jsonb_build_object('field_name',f.name,'scene_date',n.scene_date,'previous_date',p.scene_date) FROM monitoring_alerts a JOIN fields f ON f.id=a.field_id AND f.user_id=a.user_id JOIN analyses n ON n.id=a.analysis_id AND n.user_id=a.user_id JOIN analyses p ON p.id=a.previous_id AND p.user_id=a.user_id WHERE a.user_id=$1 ORDER BY a.created_at DESC LIMIT 100")
        .bind(user.id).fetch_all(&mut *tx).await?;
    Ok(Json(json!(rows)))
}

pub async fn acknowledge(
    State(app): State<App>,
    Extension(user): Extension<User>,
    Path(id): Path<Uuid>,
) -> Result<Json<Value>, ApiError> {
    let mut tx = tenant_tx(&app.pool, user.id).await?;
    if sqlx::query(
        "UPDATE monitoring_alerts SET read_at=coalesce(read_at,now()) WHERE id=$1 AND user_id=$2",
    )
    .bind(id)
    .bind(user.id)
    .execute(&mut *tx)
    .await?
    .rows_affected()
        == 0
    {
        return Err(ApiError::missing());
    }
    tx.commit().await?;
    Ok(Json(json!({"saved":true})))
}

#[derive(FromRow)]
struct Due {
    user_id: Uuid,
    field_id: Uuid,
    generation: Uuid,
    season_start: NaiveDate,
    season_end: NaiveDate,
}

/// Durable weekly schedule. Locks prevent duplicate reservations across workers.
pub async fn schedule(app: &App) -> anyhow::Result<()> {
    let mut tx = worker_tx(&app.pool).await?;
    let acquired: bool = sqlx::query_scalar("SELECT pg_try_advisory_xact_lock(724191035)")
        .fetch_one(&mut *tx)
        .await?;
    if !acquired {
        return Ok(());
    }
    let due: Vec<Due>=sqlx::query_as("SELECT user_id,field_id,generation,season_start,season_end FROM monitoring WHERE enabled AND next_run<=now() ORDER BY next_run LIMIT 100 FOR UPDATE SKIP LOCKED")
        .fetch_all(&mut *tx).await?;
    let today = Utc::now().date_naive();
    for m in due {
        let to = today.pred_opt().expect("date has predecessor");
        if today > m.season_end {
            sqlx::query(
                "UPDATE monitoring SET enabled=false,state='season_finished' WHERE field_id=$1",
            )
            .bind(m.field_id)
            .execute(&mut *tx)
            .await?;
            continue;
        }
        if to < m.season_start {
            sqlx::query("UPDATE monitoring SET next_run=now()+interval '1 day',state='waiting_season' WHERE field_id=$1").bind(m.field_id).execute(&mut *tx).await?;
            continue;
        }
        let remaining: i32 = sqlx::query_scalar(
            "SELECT analysis_limit-used-reserved FROM accounts WHERE id=$1 FOR UPDATE",
        )
        .bind(m.user_id)
        .fetch_one(&mut *tx)
        .await?;
        let busy: bool=sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM analyses WHERE user_id=$1 AND field_id=$2 AND origin='automatic' AND status IN ('queued','running'))").bind(m.user_id).bind(m.field_id).fetch_one(&mut *tx).await?;
        if remaining <= 0 || busy {
            sqlx::query(
                "UPDATE monitoring SET next_run=now()+interval '1 hour',state=$2 WHERE field_id=$1",
            )
            .bind(m.field_id)
            .bind(if busy {
                "processing"
            } else {
                "quota_exhausted"
            })
            .execute(&mut *tx)
            .await?;
            continue;
        }
        let from = (to - chrono::Duration::days(6)).max(m.season_start);
        let key = format!("auto:{}:{}:{}", m.field_id, m.generation, to);
        let inserted=sqlx::query("INSERT INTO analyses(id,user_id,field_id,field_revision,geometry,date_from,date_to,max_cloud,origin,mode,idempotency_key,fingerprint,monitor_generation,report_context) SELECT $1,f.user_id,f.id,f.revision,f.geometry,$2,$3,40,'automatic','satellite',$4,$4,$5,jsonb_build_object('field_name',f.name,'property_name',p.name,'crop',m.crop,'stage',m.stage) FROM fields f JOIN properties p ON p.id=f.property_id AND p.user_id=f.user_id JOIN monitoring m ON m.field_id=f.id AND m.user_id=f.user_id WHERE f.id=$6 AND f.user_id=$7 ON CONFLICT(user_id,idempotency_key) DO NOTHING")
            .bind(Uuid::new_v4()).bind(from).bind(to).bind(key).bind(m.generation).bind(m.field_id).bind(m.user_id).execute(&mut *tx).await?.rows_affected();
        if inserted == 1 {
            sqlx::query("UPDATE accounts SET reserved=reserved+1 WHERE id=$1")
                .bind(m.user_id)
                .execute(&mut *tx)
                .await?;
        }
        sqlx::query("UPDATE monitoring SET next_run=now()+interval '7 days',state='scheduled' WHERE field_id=$1").bind(m.field_id).execute(&mut *tx).await?;
    }
    tx.commit().await?;
    Ok(())
}

/// Compare only satellite observations from the current configuration and geometry.
pub async fn evaluate(tx: &mut Transaction<'_, Postgres>, id: Uuid) -> Result<(), sqlx::Error> {
    sqlx::query("INSERT INTO monitoring_alerts(id,user_id,field_id,analysis_id,previous_id,previous_mean,current_mean) SELECT $2,n.user_id,n.field_id,n.id,p.id,(p.statistics->>'mean')::float8,(n.statistics->>'mean')::float8 FROM analyses n JOIN monitoring m ON m.field_id=n.field_id AND m.user_id=n.user_id AND m.enabled AND m.stage IN ('vegetative','reproductive') AND m.generation=n.monitor_generation JOIN fields f ON f.id=n.field_id AND f.user_id=n.user_id AND f.revision=n.field_revision JOIN LATERAL (SELECT a.* FROM analyses a WHERE a.user_id=n.user_id AND a.field_id=n.field_id AND a.monitor_generation=n.monitor_generation AND a.field_revision=n.field_revision AND a.status='completed' AND a.mode='satellite' AND a.scene_date<n.scene_date AND a.scene_date>=n.scene_date-30 AND a.scene_date>=m.season_start AND (a.statistics->>'valid_percent')::float8>=90 ORDER BY a.scene_date DESC,a.finished_at DESC LIMIT 1) p ON true WHERE n.id=$1 AND n.status='completed' AND n.mode='satellite' AND n.scene_date BETWEEN m.season_start AND m.season_end AND (n.statistics->>'valid_percent')::float8>=90 AND (p.statistics->>'mean')::float8-(n.statistics->>'mean')::float8>=m.drop_threshold ON CONFLICT(analysis_id) DO NOTHING")
        .bind(id).bind(Uuid::new_v4()).execute(&mut **tx).await?;
    sqlx::query("UPDATE monitoring m SET state=CASE WHEN m.stage IN ('maturation','harvest') THEN 'alerts_suspended' WHEN (n.statistics->>'valid_percent')::float8<90 OR n.scene_date IS NULL THEN 'insufficient_quality' WHEN EXISTS(SELECT 1 FROM monitoring_alerts WHERE analysis_id=n.id) THEN 'attention' ELSE 'observed' END FROM analyses n WHERE n.id=$1 AND m.field_id=n.field_id AND m.user_id=n.user_id AND m.generation=n.monitor_generation AND m.enabled")
        .bind(id).execute(&mut **tx).await?;
    Ok(())
}
