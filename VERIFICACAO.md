# Verificação técnica

Verificação local realizada em 14/10/2026, em x86_64, com Rust 1.99.0.

## Código e execução

- `cargo fmt --check` aprovado.
- `cargo clippy --locked --all-targets -- -D warnings` aprovado.
- 14 testes de CAR, CRS e pipeline aprovados.
- Um teste de integração SaaS com PostgreSQL/PostGIS real aprovado.
- Imagem Docker construída e servidor/worker executados em containers.
- Servidor local com healthcheck saudável; manifestação de produção validada.

## Isolamento e consistência

O teste de integração usa banco temporário e role sem SUPERUSER/BYPASSRLS.
Valida duas contas, negação de leitura/escrita/download cruzados, RLS forçado,
CSRF/Origin, snapshots após edição, idempotência, recuperação de leases,
liberação de reserva após falha e cotas sob concorrência. Inclui upload CAR
acima do limite de JSON, dentro do limite específico de arquivo.

## Dados e sistema de coordenadas

- Importação CAR: camadas ZIP internas, seleção da área total sem duplicar
  área líquida/reserva, codificações, CRS, limites e rejeição de pacotes inválidos.
- Migration SIRGAS 2000 testada sobre esquema anterior com cadastro e job pendente.
  Preserva IDs, revisões, cotas, geometrias e referências dos produtos históricos.
- Cadastro/snapshots em EPSG:4674; GeoJSON público em WGS84, convertido na fronteira.
- Exportação SIRGAS 2000/UTM, fuso/hemisfério automático e pixels de 10 m.
- Referências PROJ conferidas nos fusos 23S, 21S e 22N, com erro inferior a 1 mm.
- Reprojeção por vizinho mais próximo validada com NumPy, Rasterio/GDAL, PROJ/pyproj
  e Shapely; mantém nodata, buracos e máscara externa. Estatísticas na grade original.
- PDFs validados por parser estrito e inspeção visual após renderização com Poppler.
- Integração Copernicus OAuth/Process API validada localmente com observações reais,
  incluindo proveniência da cena, produtos e download autenticado.

Dados privados, credenciais, ZIPs CAR e produtos usados nos testes locais não fazem
parte do repositório. Os fixtures versionados são sintéticos.

## Reproduzir

```sh
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
python3 scripts/setup-dev.py
docker compose up -d --wait postgres
scripts/test-saas.sh
```

O teste SaaS é ignorado no `cargo test` comum porque exige um banco dedicado;
o script o executa explicitamente e remove somente o banco temporário criado.
O workflow GitHub Actions executa essas verificações e um smoke test da imagem.

Validação ARM64 e implantação na OCI ainda estão pendentes. Requisitos e limites
atuais de operação estão descritos no README e no documento de arquitetura.
