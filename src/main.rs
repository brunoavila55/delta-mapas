use anyhow::{Context, Result, ensure};
use chrono::NaiveDate;
use clap::{Parser, Subcommand};
use delta_analysis::{area::Area, provider, raster, render};
use serde_json::json;
use std::{
    fs,
    path::{Path, PathBuf},
};

#[derive(Parser)]
#[command(version, about = "Prova de NDVI em Rust para o novo SaaS")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Converte o limite de um ZIP do CAR para GeoJSON, sem enviar dados ao provedor.
    ImportCar {
        #[arg(long)]
        input: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
    /// Verifica a prontidão do servidor local (para o container).
    HealthCheck,
    /// Inicia o servidor web do SaaS.
    Serve,
    /// Processa a fila persistente no PostgreSQL.
    Worker,
    /// Aplica migrations antes de iniciar servidor e worker.
    Migrate,
    /// Cria conta individual; senha em DELTA_INITIAL_PASSWORD.
    CreateUser {
        #[arg(long)]
        email: String,
    },
    /// Cria bandas sintéticas e passa pelo pipeline real, sem rede ou credenciais.
    Demo {
        #[arg(long)]
        area: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
    /// Processa um GeoTIFF Float32 com B04, B08, SCL e dataMask em EPSG:4326.
    Analyze {
        #[arg(long)]
        area: PathBuf,
        #[arg(long)]
        bands: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
    /// Obtém uma cena real via Process API (requer credenciais no ambiente).
    Fetch {
        #[arg(long)]
        area: PathBuf,
        #[arg(long)]
        from: NaiveDate,
        #[arg(long)]
        to: NaiveDate,
        #[arg(long, default_value_t = 20.0)]
        max_cloud: f64,
        #[arg(long, default_value_t = 10.0)]
        resolution: f64,
        #[arg(long)]
        output: PathBuf,
    },
}

/// Stage all products beside the destination. Errors remove incomplete output;
/// an existing result is never overwritten. One CLI run is not a SaaS job queue.
fn staged(output: &Path, task: impl FnOnce(&Path) -> Result<()>) -> Result<()> {
    ensure!(
        !output.exists(),
        "Destino já existe; use outro diretório de saída"
    );
    let parent = output
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    fs::create_dir_all(parent)?;
    let name = output
        .file_name()
        .context("Diretório de saída inválido")?
        .to_string_lossy();
    let stage = parent.join(format!(".{name}.partial-{}", std::process::id()));
    fs::create_dir(&stage)?;
    let result = task(&stage).and_then(|()| {
        ensure!(!output.exists(), "Destino criado por outra execução");
        fs::rename(&stage, output)?;
        Ok(())
    });
    if result.is_err() {
        let _ = fs::remove_dir_all(&stage);
    }
    result
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    if let Command::ImportCar { input, output } = &cli.command {
        ensure!(
            fs::metadata(input)?.len() <= delta_analysis::car::MAX_UPLOAD as u64,
            "ZIP excede 10 MB"
        );
        let report = delta_analysis::car::import(&fs::read(input)?)?;
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(output)?;
        use std::io::Write;
        file.write_all(&serde_json::to_vec_pretty(&report.geometry)?)?;
        println!(
            "Área importada: {:.4} ha; {} -> {}; {} de {} feições utilizadas.",
            report.area_ha,
            report.source_crs,
            report.target_crs,
            report.selected_features,
            report.source_features
        );
        return Ok(());
    }
    if matches!(cli.command, Command::HealthCheck) {
        let response = reqwest::blocking::Client::builder()
            .timeout(std::time::Duration::from_secs(3))
            .build()?
            .get("http://127.0.0.1:3010/health/ready")
            .send()?;
        ensure!(response.status().is_success(), "Servidor não está pronto");
        return Ok(());
    }
    match &cli.command {
        Command::Serve | Command::Worker | Command::Migrate | Command::CreateUser { .. } => {
            let runtime = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()?;
            return runtime.block_on(async {
                match cli.command {
                    Command::Serve => delta_analysis::saas::serve().await,
                    Command::Worker => delta_analysis::saas::worker::run().await,
                    Command::Migrate => delta_analysis::saas::migrate().await,
                    Command::CreateUser { email } => delta_analysis::saas::provision(email).await,
                    _ => unreachable!(),
                }
            });
        }
        _ => {}
    }
    let (output, stats) = match cli.command {
        Command::ImportCar { .. } => unreachable!(),
        Command::HealthCheck => unreachable!(),
        Command::Serve | Command::Worker | Command::Migrate | Command::CreateUser { .. } => {
            unreachable!()
        }
        Command::Demo { area, output } => {
            let area = Area::read(&area)?;
            let mut summary = String::new();
            staged(&output, |dir| {
                raster::write_demo(&dir.join("bands.tif"), &area)?;
                let analysis =
                    raster::calculate(&raster::read_bands(&dir.join("bands.tif"))?, &area)?;
                summary = serde_json::to_string_pretty(&analysis.statistics)?;
                render::write_products(
                    dir,
                    &analysis,
                    &area,
                    json!({"kind": "synthetic", "description": "Dados matemáticos de teste; não são observações de satélite"}),
                )
            })?;
            (output, summary)
        }
        Command::Analyze {
            area,
            bands,
            output,
        } => {
            let area = Area::read(&area)?;
            let analysis = raster::calculate(&raster::read_bands(&bands)?, &area)?;
            let summary = serde_json::to_string_pretty(&analysis.statistics)?;
            staged(&output, |dir| {
                render::write_products(
                    dir,
                    &analysis,
                    &area,
                    json!({"kind": "local", "description": "Bandas fornecidas localmente; data e origem não verificadas"}),
                )
            })?;
            (output, summary)
        }
        Command::Fetch {
            area,
            from,
            to,
            max_cloud,
            resolution,
            output,
        } => {
            let area = Area::read(&area)?;
            let mut summary = String::new();
            staged(&output, |dir| {
                let source = provider::download(&area, from, to, max_cloud, resolution, dir)?;
                let bands = raster::read_bands(&dir.join("bands.tif"))?;
                let expected = raster::Grid::from_area(&area, bands.grid.width, bands.grid.height);
                ensure!(
                    (bands.grid.west - expected.west).abs() < 1e-8
                        && (bands.grid.north - expected.north).abs() < 1e-8
                        && (bands.grid.dx - expected.dx).abs() < 1e-8
                        && (bands.grid.dy - expected.dy).abs() < 1e-8,
                    "Grade do provedor diverge da área solicitada"
                );
                let analysis = raster::calculate(&bands, &area)?;
                summary = serde_json::to_string_pretty(&analysis.statistics)?;
                render::write_products(dir, &analysis, &area, source)
            })?;
            (output, summary)
        }
    };
    println!("Resultado: {}\n{}", output.display(), stats);
    Ok(())
}
