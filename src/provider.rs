use crate::area::Area;
use anyhow::{Context, Result, ensure};
use chrono::NaiveDate;
use reqwest::blocking::{Client, Response};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    env, fs,
    io::{Cursor, Read},
    path::Path,
    time::Duration,
};

const TOKEN_URL: &str =
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token";
const PROCESS_URL: &str = "https://sh.dataspace.copernicus.eu/process/v1";
const MAX_RESPONSE: u64 = 80_000_000;

// Select one actual tile instead of silently creating a multi-date mosaic.
// This is deliberately scoped to small areas; multi-tile coverage is future work.
const EVALSCRIPT: &str = r#"//VERSION=3
function setup() {
  return {
    input: [{bands: ["B04", "B08", "SCL", "dataMask"], units: ["REFLECTANCE", "REFLECTANCE", "DN", "DN"]}],
    output: {id: "bands", bands: 4, sampleType: "FLOAT32", nodataValue: -9999},
    mosaicking: "TILE"
  };
}
function preProcessScenes(collections) {
  collections.scenes.tiles.sort(function(a,b) {
    return a.cloudCoverage - b.cloudCoverage || new Date(b.date) - new Date(a.date);
  });
  collections.scenes.tiles = collections.scenes.tiles.slice(0, 1);
  return collections;
}
function evaluatePixel(samples) {
  if (!samples.length || samples[0].dataMask !== 1) return [-9999, -9999, 0, 0];
  var s = samples[0];
  return [s.B04, s.B08, s.SCL, s.dataMask];
}
function updateOutputMetadata(scenes, inputMetadata, outputMetadata) {
  outputMetadata.userData = {tiles: scenes.tiles, serviceVersion: inputMetadata.serviceVersion};
}
"#;

#[derive(Deserialize)]
struct Token {
    access_token: String,
}

pub fn request_payload(
    area: &Area,
    from: NaiveDate,
    to: NaiveDate,
    cloud: f64,
    resolution: f64,
) -> Result<Value> {
    ensure!(
        from <= to,
        "Data inicial deve ser anterior ou igual à final"
    );
    ensure!(
        cloud.is_finite() && (0.0..=100.0).contains(&cloud),
        "Nuvens deve estar entre 0 e 100"
    );
    let (width, height) = area.grid_size(resolution)?;
    Ok(json!({
        "input": {
            "bounds": {"bbox": area.bounds, "geometry": area.geometry,
                "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
            "data": [{"type": "sentinel-2-l2a", "dataFilter": {
                "timeRange": {"from": format!("{from}T00:00:00Z"), "to": format!("{to}T23:59:59Z")},
                "maxCloudCoverage": cloud, "mosaickingOrder": "leastCC"
            }, "processing": {"upsampling": "NEAREST", "downsampling": "NEAREST"}}]
        },
        "output": {"width": width, "height": height, "responses": [
            {"identifier": "bands", "format": {"type": "image/tiff"}},
            {"identifier": "userdata", "format": {"type": "application/json"}}
        ]},
        "evalscript": EVALSCRIPT
    }))
}

fn bounded(mut response: Response, max: u64) -> Result<Vec<u8>> {
    ensure!(
        response.status().is_success(),
        "Provedor retornou HTTP {}",
        response.status().as_u16()
    );
    if let Some(length) = response.content_length() {
        ensure!(length <= max, "Resposta excede o limite de download");
    }
    let mut bytes = Vec::new();
    (&mut response).take(max + 1).read_to_end(&mut bytes)?;
    ensure!(
        !bytes.is_empty() && bytes.len() as u64 <= max,
        "Resposta vazia ou acima do limite"
    );
    Ok(bytes)
}

pub fn unpack(bytes: &[u8]) -> Result<(Vec<u8>, Value)> {
    let mut archive = tar::Archive::new(Cursor::new(bytes));
    let (mut raster, mut metadata) = (None, None);
    for (index, entry) in archive.entries()?.enumerate() {
        ensure!(index < 8, "Resposta do provedor contém arquivos demais");
        let mut entry = entry?;
        let path = entry.path()?.into_owned();
        ensure!(
            entry.header().entry_type().is_file(),
            "Tipo de arquivo inesperado do provedor"
        );
        let name = path.to_str().context("Nome de arquivo inválido")?;
        let limit = match name {
            "bands.tif" => MAX_RESPONSE,
            "userdata.json" => 1_000_000,
            _ => anyhow::bail!("Arquivo inesperado na resposta do provedor"),
        };
        ensure!(entry.size() <= limit, "Arquivo do provedor excede o limite");
        let mut data = Vec::new();
        entry.read_to_end(&mut data)?;
        match name {
            "bands.tif" => {
                ensure!(raster.is_none(), "Raster duplicado");
                raster = Some(data);
            }
            "userdata.json" => {
                ensure!(metadata.is_none(), "Metadados duplicados");
                metadata = Some(serde_json::from_slice::<Value>(&data)?);
            }
            _ => unreachable!(),
        }
    }
    let metadata = metadata.context("Provedor não retornou metadados de cena")?;
    let tiles = metadata["tiles"]
        .as_array()
        .context("Metadados sem lista de cenas")?;
    ensure!(
        tiles.len() == 1,
        "Nenhuma cena adequada ou seleção de cena ambígua"
    );
    ensure!(
        tiles[0]["date"].as_str().is_some() && tiles[0]["shId"].is_number(),
        "Cena sem data ou identificador"
    );
    Ok((raster.context("Provedor não retornou raster")?, metadata))
}

pub fn download(
    area: &Area,
    from: NaiveDate,
    to: NaiveDate,
    cloud: f64,
    resolution: f64,
    directory: &Path,
) -> Result<Value> {
    let payload = request_payload(area, from, to, cloud, resolution)?;
    let id =
        env::var("COPERNICUS_CLIENT_ID").context("Configure COPERNICUS_CLIENT_ID no ambiente")?;
    let secret = env::var("COPERNICUS_CLIENT_SECRET")
        .context("Configure COPERNICUS_CLIENT_SECRET no ambiente")?;
    ensure!(
        !id.trim().is_empty() && !secret.trim().is_empty(),
        "Credenciais vazias"
    );
    let client = Client::builder()
        .connect_timeout(Duration::from_secs(15))
        .timeout(Duration::from_secs(180))
        .redirect(reqwest::redirect::Policy::none())
        .build()?;
    let token: Token = serde_json::from_slice(&bounded(
        client
            .post(TOKEN_URL)
            .form(&[
                ("grant_type", "client_credentials"),
                ("client_id", id.as_str()),
                ("client_secret", secret.as_str()),
            ])
            .send()
            .context("Falha ao autenticar com o provedor")?,
        64_000,
    )?)
    .context("Resposta de autenticação inválida")?;
    let bytes = bounded(
        client
            .post(PROCESS_URL)
            .bearer_auth(&token.access_token)
            .header("Accept", "application/tar")
            .json(&payload)
            .send()
            .context("Falha ao solicitar as bandas")?,
        MAX_RESPONSE,
    )?;
    let (raster, metadata) = unpack(&bytes)?;
    fs::write(directory.join("bands.tif"), raster)?;
    fs::write(
        directory.join("source.json"),
        serde_json::to_vec_pretty(&metadata)?,
    )?;
    Ok(
        json!({"kind": "satellite", "provider": "copernicus-sentinel-hub", "metadata": metadata,
        "requested_from": from, "requested_to": to, "max_cloud_percent": cloud,
        "nominal_resolution_m": resolution, "selection": "single_tile_least_cloud_then_latest"}),
    )
}
