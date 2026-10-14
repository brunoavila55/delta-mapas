# Delta Mapas

Aplicação de mapas agrícolas em **Rust/Axum e PostgreSQL/PostGIS**. Permite cadastrar
propriedades e talhões, importar CAR ou GeoJSON, solicitar NDVI e baixar resultados.

## Funcionalidades

- Contas individuais, sessões persistentes e dados isolados por usuário.
- Importação de ZIP do CAR e GeoJSON; o CAR representa o limite do imóvel inteiro.
- Análises Sentinel-2 via Copernicus, com fila, histórico e controle de uso.
- Exportação GeoTIFF, PNG, PDF e JSON; novos produtos em SIRGAS 2000/UTM.
- Demonstração com dados sintéticos, sem credenciais de satélite.

A interface atual usa HTML/CSS/JavaScript servido pelo backend, sem framework frontend.
Recuperação de senha, cobrança e monitoramento automático ainda estão pendentes.

## Executar localmente

```sh
python3 scripts/setup-dev.py
docker compose up -d --build
```

Abra **http://127.0.0.1:3010**. O script cria `.env` sem substituir configurações
existentes; o Compose inicia banco, migrations, servidor e worker.

Para análises reais, configure `COPERNICUS_CLIENT_ID` e `COPERNICUS_CLIENT_SECRET`
no `.env` e recrie os serviços:

```sh
docker compose up -d --no-deps --force-recreate app worker
```

## Verificar

```sh
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
scripts/test-saas.sh
```

O último comando exige PostgreSQL/PostGIS e usa um banco temporário isolado.
O GitHub Actions também executa essas verificações e uma demonstração em container.

## Produção e documentação

O `compose.prod.yml` prepara servidor, worker, banco e HTTPS com Caddy. Configure
`.env.prod` a partir de `.env.prod.example`; a implantação OCI ainda está pendente.

- [Guia técnico e operação](docs/GUIA-TECNICO.md)
- [Arquitetura e próximas entregas](MVP-e-arquitetura.md)
- [Verificação e limites](VERIFICACAO.md)
