# Guia técnico do Delta Mapas

O Delta Mapas usa Rust/Axum e PostgreSQL/PostGIS. Há uma aplicação web com login
individual, propriedades, talhões, solicitação de NDVI, histórico e downloads privados.
Cada usuário é um tenant: não existem organizações, membros ou login de empresa.
Cobrança recorrente, recuperação de senha e monitoramento automático ainda não estão implementados.

## Iniciar a aplicação local

```sh
python3 scripts/setup-dev.py
docker compose up -d --build
```

Abra **http://127.0.0.1:3010** e crie sua conta. O Compose inicia PostgreSQL/PostGIS,
migrations, servidor e worker, com imagens iguais para os três últimos modos.
Migrations são executadas antes dos consumidores. O banco só publica uma porta local
de desenvolvimento (5439); não usa nem altera outros bancos existentes no computador.

O ambiente local habilita demonstrações identificadas como **dados sintéticos**.
Cadastre uma propriedade, importe seu ZIP do CAR ou GeoJSON, solicite a demonstração e consulte o
mapa e os arquivos. As análises de satélite reais precisam de credenciais configuradas
no servidor e no worker. O limite inicial é de dez análises por conta, sem renovação
mensal nem cobrança nesta etapa.

Para desenvolver sem recompilar containers a cada alteração:

```sh
docker compose up -d --wait postgres
scripts/dev.sh migrate
scripts/dev.sh serve
# Em outro terminal:
scripts/dev.sh worker
```

Não execute o servidor Cargo e o servidor Compose ao mesmo tempo na porta 3010.
Os modos Cargo e Compose usam storages diferentes: diretório local e volume Docker,
respectivamente. Escolha um modo por instalação; trocar só o caminho de storage não
migra arquivos de análises existentes.

Para provisionar uma conta com o cadastro público fechado, use `create-user --email`
com `DELTA_INITIAL_PASSWORD` definido temporariamente no ambiente. O comando preserva
a senha de uma conta já existente.

## Isolamento e execução

- Sessões persistentes: token aleatório em cookie HttpOnly, SameSite=Strict e Secure
  em produção; somente o SHA-256 do token é armazenado no banco.
- Senhas com Argon2id, CSRF por token de sessão e validação de Origin.
- Limites de tentativas por e-mail e por IP da conexão. Atrás do proxy, o limite por
  conexão agrega os clientes; cabeçalho X-Forwarded-For não é confiado indiscriminadamente.
- `user_id` em propriedades, talhões e análises; todas as rotas filtram pelo dono.
- PostgreSQL RLS com FORCE nas três tabelas operacionais. O contexto de usuário é
  local à transação; consultas sem contexto não veem linhas. O app recusa roles
  SUPERUSER/BYPASSRLS. Chaves estrangeiras compostas impedem relações entre donos distintos.
- Worker usa um contexto interno para consumir a fila de todas as contas. Servidor
  e worker são serviços confiáveis, não usuários com acesso direto ao SQL.
- Solicitação e reserva são transacionais; Idempotency-Key evita duplicar uma mesma
  solicitação. Uma chave reapresentada com conteúdo diferente retorna conflito.
- Snapshot de geometria e revisão por análise; editar um talhão preserva análises antigas.
- Posse temporária, heartbeat, recuperação de tarefas interrompidas e até três tentativas,
  com espera progressiva. Cada tentativa usa um diretório próprio.
- Conclusão e consumo são gravados em uma única transação, condicionada à posse atual;
  falha definitiva libera a reserva. Tentativas vencidas não publicam resultados.
- Os downloads verificam sessão e dono, não expõem o volume como diretório estático.
- Origem `manual`/`automatic` existe no banco; a API pública só cria pedidos manuais.

Reutilização de resultado por cena com chaves de solicitação diferentes ainda não está
implementada. Arquivos de tentativas perdidas por queda podem ficar órfãos; coleta
periódica de órfãos é uma pendência operacional antes da liberação pública.

## O que está implementado

- Entrada GeoJSON Polygon/MultiPolygon ou Feature em WGS84, com validação geométrica.
- Importação direta de ZIP do CAR, incluindo arquivos ZIP internos por camada, com
  seleção de Área do Imóvel, leitura de SHP/SHX/DBF/PRJ e cadastro em SIRGAS 2000.
- Download autenticado de B04/B08/SCL/dataMask pela Process API do Copernicus.
- Seleção de uma única tile, priorizando menor nuvem e depois data mais recente;
  metadados da tile selecionada são obtidos do próprio processamento.
- NDVI em Rust, com máscara do talhão, buracos, nuvens, sombras, nodata e valores inválidos.
- Estatísticas sobre pixels válidos, com denominador de cobertura limitado ao talhão.
- Cadastro em SIRGAS 2000/EPSG:4674; GeoJSON público convertido para WGS84.
- GeoTIFF, PNG e PDF em SIRGAS 2000/UTM, fuso automático, grade métrica de 10 m.
- JSON de proveniência distingue CRS cadastral, grade original e grade exportada.
- Saída em diretório temporário, publicado ao concluir; resultados existentes não são sobrescritos.
- Container com usuário sem privilégios, sem Python, GDAL, Redis ou Node em runtime.

## Rodar sem credenciais

Instale Rust via [rustup](https://rustup.rs/). O `rust-toolchain.toml` fixa a versão.

```sh
cargo run --locked -- demo --area examples/talhao.geojson --output output/demo
```

Os dados desse comando são **sintéticos** e o talhão é ilustrativo. Isso está indicado
no PDF, JSON e TIFF de entrada. O comando exercita o mesmo leitor, cálculo e exportação
utilizados pelas análises reais. Use outro diretório para executar novamente.

Saídas: `bands.tif`, `ndvi.tif`, `ndvi.png`, `report.pdf`, `analysis.json`.

## Importar CAR

Na tela de cadastro de talhão, selecione **Importar área: ZIP do CAR ou GeoJSON**.
O ZIP pode conter as camadas internas `Area_do_Imovel.zip`, `Cobertura_do_Solo.zip`
e `Reserva_Legal.zip`. O importador escolhe a camada Área do Imóvel e o registro da
área total pelo tema. Não soma a área líquida nem a reserva legal ao limite total.

O CAR representa o limite cadastral da propriedade inteira. A importação não identifica
automaticamente os talhões de cultivo. A área importada pode ser analisada diretamente;
talhões específicos devem ser delimitados separadamente.

Também há conversão local, sem chamadas ao Copernicus:

```sh
cargo run --locked -- import-car --input meu-car.zip --output area-imovel.geojson
```

Limites: ZIP até 10 MB, 32 MB descompactados no conjunto, 64 arquivos, até dois níveis
de ZIPs internos, 256 feições e 10 mil coordenadas na camada selecionada. Nesta versão
são aceitos PRJs WKT1 geográficos em SIRGAS 2000/EPSG:4674 ou WGS84/EPSG:4326,
em graus, com longitude/latitude. PRJ ausente ou incompatível é rejeitado; não há
adivinhação de projeção. ZIPs projetados em UTM/SAD69 exigem conversão antes de importar.

O endpoint `/api/imports/car` exige login, Origin e CSRF. A leitura é feita em memória,
sem extrair caminhos do ZIP para o disco, e não armazena o DBF nem seus atributos
pessoais. A importação retorna geometria e informações de seleção; o cadastro
persiste somente a área e o nome escolhido pelo usuário.

## Processar bandas fornecidas localmente

```sh
cargo run --locked -- analyze --area meu-talhao.geojson --bands minhas-bandas.tif --output output/local
```

Contrato: quatro bandas **intercaladas Float32**, na ordem B04, B08, SCL, dataMask.
As duas primeiras são reflectâncias, não números digitais sem conversão. GeoTIFF
north-up em EPSG:4326 com PixelIsArea e tags ModelPixelScale/ModelTiepoint.
A CLI não identifica automaticamente ordem/unidade de bandas de arquivos externos.
Data e origem são marcadas como não verificadas no resultado local.

## Obter uma análise real

Configure `COPERNICUS_CLIENT_ID` e `COPERNICUS_CLIENT_SECRET` no ambiente por meio
do seu gerenciador de segredos. Não passe segredos em argumentos nem os inclua no Git.
São credenciais OAuth de Sentinel Hub/CDSE, não chaves de S3 nem a senha da conta.

No Compose local, adicione ao `.env` da raiz deste projeto:

```dotenv
COPERNICUS_CLIENT_ID=seu_client_id
COPERNICUS_CLIENT_SECRET=seu_client_secret
```

Depois execute `docker compose up -d --no-deps --force-recreate app worker`.
Recriar os containers aplica as novas variáveis; um simples restart não atualiza
o ambiente. Na interface, selecione **NDVI · imagem de satélite** para usar o provedor.
O aplicativo solicita o access token automaticamente; não há campo para colar
um bearer token temporário. Em produção, use os mesmos campos em `.env.prod`.

```sh
cargo run --locked -- fetch --area meu-talhao.geojson --from 2026-09-01 --to 2026-09-30 --max-cloud 20 --resolution 10 --output output/real
```

Esse comando solicita processamento externo e pode consumir a quota do provedor.
Não há retries automáticos nesta prova. Falhas HTTP são retornadas sem imprimir tokens
ou corpos de autenticação. Respostas e dimensões têm limites de tamanho e tempo.

A integração já foi exercitada localmente com observações reais. Novos pedidos
dependem das credenciais e consomem a quota do provedor.

## Container de processamento

```sh
docker build -t delta-analysis:0.1.0 .
docker run --rm delta-analysis:0.1.0 --help
mkdir -p output
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/output:/data:Z" delta-analysis:0.1.0 demo --area examples/talhao.geojson --output /data/demo-container
```

O sufixo `:Z` no bind mount atende hosts com SELinux; pode ser omitido nos demais.
Não é necessário instalar bibliotecas geoespaciais no host.

O teste local usa x86_64. Build e execução ARM64 precisam de validação antes de
implantar em uma VM Ampere; não considerar a existência de uma imagem base ARM64
como prova de compatibilidade do aplicativo completo.

## Limites deliberados da prova

- Máximo de 4 milhões de pixels, 80 MB de arquivo e 10 mil coordenadas.
- Download: até 2.500 pixels por eixo; resolução nominal mínima de 10 m.
- A solicitação ao Copernicus mantém WGS84, com dimensionamento aproximado pela
  latitude central. O NDVI é calculado nessa grade e reamostrado por vizinho mais próximo
  para exportação em SIRGAS 2000/UTM de 10 m. Isso não aumenta a resolução da observação.
  Estatísticas e cobertura permanecem na grade original, indicada em `analysis.json`.
- Exportação limitada aos fusos SIRGAS 18–25S e 18–22N. Uma área usa o fuso do centro;
  extensão máxima de 1 grau por eixo. Datum SIRGAS/GRS80 com transformação estática
  para WGS84, adequada à análise de 10 m; não é um ajuste geodésico por época.
- Uma única tile selecionada pode cobrir só parte de um talhão na borda de tiles.
  O resultado mostra cobertura válida; não há preenchimento com outra cena/data.
- A porcentagem de nuvens da tile não mede nuvens especificamente no talhão.
- Classes SCL aceitas: vegetação, solo e água (4, 5, 6). Demais classes são descartadas.
- PNG mostra a grade; a composição cartográfica e legenda estão no PDF.
- Os comandos de processamento direto são locais e não passam pela conta ou pela fila.
  O servidor e o worker fazem o vínculo com o cliente e o controle de uso.

## Verificação

```sh
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
scripts/test-saas.sh
```

`scripts/verify_demo.py` compara o NDVI e as estatísticas com NumPy/Rasterio e a
exportação UTM com PROJ/pyproj e Shapely, independentes do código Rust.
Essas dependências Python são **somente QA**.

`scripts/verify_car.py` confere um CAR com PyShp, PROJ/pyproj e Shapely, comparando
geometria e área após a transformação. O ZIP privado utilizado na validação não é
incluído em fixtures ou no repositório.

```sh
python3 -m venv target/qa-venv
target/qa-venv/bin/pip install numpy rasterio pypdf pyproj shapely pyshp
target/qa-venv/bin/python scripts/verify_demo.py output/demo
```

Renderize o PDF com `pdftoppm -png -scale-to 1400 output/demo/report.pdf output/demo/report-preview`
para conferir a composição visual.

O teste SaaS cria um banco temporário com PostGIS, verifica duas contas, downloads,
RLS, recuperação de lease, reservas e concorrência, e remove apenas esse banco ao terminar.
É ignorado pelo `cargo test` comum e executado explicitamente pelo script e pelo workflow.

## Produção na OCI

`compose.prod.yml` contém servidor, worker, PostgreSQL/PostGIS e Caddy. Diferentemente
do Compose local, não publica o banco ou o servidor diretamente, exige cookies HTTPS,
fecha cadastro público e desativa demonstrações. Copie `.env.prod.example` e informe
domínio, imagem de release já publicada, senhas independentes e credenciais do provedor.

```sh
docker compose --env-file .env.prod -f compose.prod.yml config --quiet
docker compose --env-file .env.prod -f compose.prod.yml up -d
```

O manifesto foi preparado para a OCI, mas ainda não foi implantado numa VM.
Validar a arquitetura da VM, o provedor real, DNS/HTTPS e recuperação de backup é
necessário antes de liberar clientes. Não apagar volumes durante atualizações.

## Próxima entrega

Adicionar recuperação de acesso, validação de e-mail, planos/pagamentos
e backup/restauração. O agendador automático
entrará pela mesma fila e pipeline; ainda não há configuração de acompanhamento.

Referências: [Process API](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/ApiReference.html),
[Sentinel-2 L2A](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S2L2A.html),
[metadados de processamento](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/UserGuides/Metadata.html).


## Referencial SIRGAS 2000

A migration `0002_sirgas2000.sql` transforma os campos existentes e os snapshots
geométricos das análises para EPSG:4674, preservando IDs, revisões, donos e cotas.
O PostGIS calcula hectares no elipsoide GRS80. Geometrias de cadastro e snapshots
carregam `geometry_crs=4674`. A API web continua usando GeoJSON RFC 7946/WGS84;
`storage_crs` distingue o sistema do cadastro do sistema de transporte.
O retorno da importação CAR inclui `cadastral_geometry`/`cadastral_crs`, além do
GeoJSON WGS84 usado pelo navegador.

Pare servidor e worker antes de aplicar essa migration e iniciar os novos binários:
versões antigas interpretam os snapshots como WGS84. Faça um backup antes da atualização.
Os arquivos de análises concluídas ficam intactos no CRS original. Só os novos produtos
usam `schema_version=2` / `ndvi-v2-sirgas` com exportação métrica; não há regravação silenciosa
nem novo download de satélite para converter o cadastro.
