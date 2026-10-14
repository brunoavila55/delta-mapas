# Verificação

Registro das validações locais realizadas em 13–14/10/2026; não representa uma nova
execução de todos os testes a cada edição deste documento.

## Validado

- Formatação, Clippy e testes de CAR, CRS e processamento Rust.
- Integração com PostgreSQL/PostGIS: isolamento entre contas, CSRF, RLS, fila,
  idempotência, concorrência, recuperação de tarefas, cotas e downloads privados.
- Fluxo no navegador: login, cadastro, importação CAR, solicitação e consulta de NDVI.
- Processamento sintético e análises reais via Copernicus.
- Produtos conferidos com NumPy/Rasterio, PROJ/pyproj e Shapely; PDF verificado
  por parser e inspeção visual.
- Migração cadastral para SIRGAS 2000 e exportação UTM de 10 m; produtos históricos preservados.
- Execução em Docker x86_64 e configuração Compose.

Os arquivos CAR privados, credenciais e artefatos locais não fazem parte do repositório.
A conferência de produtos reais verifica a consistência do GeoTIFF e das estatísticas;
as bandas originais são removidas pelo worker após o processamento.

## Reproduzir

```sh
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
scripts/test-saas.sh
```

Para QA independente de geometria e produtos, consulte os scripts `verify_car.py`
e `verify_demo.py` e as instruções do [guia técnico](docs/GUIA-TECNICO.md).

## Pendências

- Compatibilidade ARM64 e implantação OCI.
- Backup/restauração e coleta de arquivos órfãos.
- Recuperação de acesso, verificação de e-mail, cobrança e monitoramento automático.
- Cobertura de talhões na borda de tiles e reutilização de resultados por cena.
