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
- Recuperação de acesso, verificação de e-mail, cobrança.
- Cobertura de talhões na borda de tiles e reutilização de resultados por cena.

## Acompanhamento semanal (14/10/2026)

Validação em banco temporário PostGIS: migration 0003, isolamento de configurações
e alertas, CSRF, agendadores concorrentes, reserva única, espera por falta de saldo,
comparação idempotente e exclusão de cenas repetidas, cobertura insuficiente,
geometria diferente, configuração de outra safra ou fase de maturação.
Também foram verificadas espera pelo início da safra e desativação ao encerrá-la. Observações conhecidas são
inseridas no teste; esta verificação não faz solicitações ao provedor.

Interface verificada no desktop e no celular: ativação, configuração, pausa,
consulta do resultado e marcação de alerta como conferido. Build TypeScript/Vite,
formatação Rust, Clippy e testes de processamento também passaram.

## Cartografia e relatório (14/10/2026)

Novas análises geram uma prancha cartográfica independente e um relatório de duas
páginas. Os PDFs foram renderizados e inspecionados visualmente, com fontes embutidas.
Testes de integração incluem download privado dos dois PDFs e preservação do nome
do talhão após edição. A conferência científica independente compara distribuição
por faixas com NumPy e a escala declarada com o tamanho físico do raster no PDF.
