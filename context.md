# Contexto do Delta Mapas

Este documento é o ponto de retomada do desenvolvimento. Ele resume o produto, as decisões que já
foram tomadas, o que está executável e qual é a próxima entrega. Detalhes de contratos permanecem em
`docs/`.

## O que é o projeto

Delta Mapas é a base de um SaaS multitenant de sensoriamento remoto agrícola. O produto permitirá
que produtores, agrônomos, consultorias e empresas de agricultura de precisão cadastrem propriedades
rurais, selecionem uma área e gerem mapas cartográficos a partir de imagens de satélite.

O primeiro índice é NDVI, calculado com Sentinel-2 Level-2A:

```text
NDVI = (B08 - B04) / (B08 + B04)
```

A arquitetura está preparada para receber novos índices, relatórios e comparações temporais sem
colocar lógica geoespacial dentro de views ou tasks Celery.

## Arquitetura atual

```text
React + Vite
      ↓ /api/v1
Django REST Framework + GeoDjango
      ↓
PostgreSQL + PostGIS, isolado por schemas de tenant

Django ──enfileira──→ Celery ──broker/resultados──→ Redis
                           │
                           ├── Copernicus STAC: descoberta da cena
                           ├── Sentinel Hub Process API via OAuth2: recorte raster
                           ├── Rasterio + NumPy: máscaras e NDVI
                           ├── Matplotlib + PyProj: renderer PNG/PDF
                           └── MinIO: produtos finais privados
```

Componentes principais:

- Django 5.2, DRF, GeoDjango e `django-tenants`;
- PostgreSQL/PostGIS;
- Celery com concorrência 1 e Redis;
- MinIO privado por meio de `django-storages`;
- React, TypeScript, Vite, Tailwind e MapLibre;
- NumPy e Rasterio para o pipeline geoespacial;
- `pystac-client` para o catálogo Copernicus.

## Multitenancy e segurança

Identidade, tenants e memberships vivem no schema `public`. Propriedades, jobs, mapas e billing
vivem no schema de cada tenant. Um usuário pode participar de várias organizações.

Invariantes importantes:

- uma request nunca deve atravessar o schema do tenant atual;
- UUIDs são usados como identificadores públicos;
- geometria e área são validadas no backend;
- uploads são tratados como entrada não confiável e removidos após o uso;
- segredos existem somente em variáveis de ambiente;
- imagens Sentinel brutas e rasters intermediários nunca são persistidos permanentemente;
- somente PNG/PDF finais devem chegar ao MinIO.

## O que já está implementado

### Fundação

- stack Docker com backend, worker, PostgreSQL/PostGIS, Redis, MinIO e frontend;
- healthchecks, OpenAPI/Swagger, logging estruturado e seed `setup_dev`;
- compatibilidade das dependências novas confirmada para Linux ARM64.

### Autenticação e propriedades

- login, refresh, logout e `/me` com JWT;
- membership ativa por tenant;
- CRUD de propriedades GeoJSON;
- normalização para `MultiPolygon` em EPSG:4326;
- área calculada no backend em projeção equal-area;
- importação segura de shapefile ZIP usando diretório temporário.

### Billing e jobs

- conta com saldos disponível e reservado;
- ledger imutável e idempotente;
- preço configurável por índice;
- reserva, captura e liberação transacionais com locks;
- criação idempotente de `MapJob` por header `Idempotency-Key`;
- listagem e detalhe de jobs;
- compensação automática quando a fila ou o processamento falha.

### Sentinel e NDVI

- busca na collection `sentinel-2-l2a` por geometria e período;
- filtro de cobertura máxima de nuvens;
- validação dos assets lógicos B04, B08 e SCL;
- seleção determinística por menor nuvem e cena mais recente;
- registro de `stac_item_id` no job;
- OAuth2 Client Credentials com token em memória, cache, renovação antecipada e timeouts;
- chamada à Sentinel Hub Process API oficial, com retry e classificação de falhas;
- requisição de B04, B08, SCL e `dataMask` em uma grade UTM comum de 10 metros;
- limites preventivos de pixels e bytes, download streaming e limpeza garantida dos temporários;
- `BaseIndexProcessor` extensível;
- `NDVIProcessor` vetorizado com máscara SCL, `dataMask`, nodata, NaN e divisão por zero;
- integração do pipeline raster à task Celery e estados de progresso até 100%;
- renderer cartográfico A4 paisagem com paleta NDVI, legenda, grade geográfica, escala, norte,
  metadados da cena e identificação Delta Mapas;
- persistência privada de PNG/PDF no MinIO e downloads autenticados pela API;
- criação idempotente de `GeneratedMap`, conclusão do job e captura transacional do crédito.

### Frontend operacional

- autenticação JWT, renovação coordenada da sessão e proteção de rotas;
- painel com saldo, propriedades, processamentos recentes e último produto;
- desenho de polígonos, múltiplos componentes e furos por cliques, com edição de todos os vértices,
  remoção individual de anéis/componentes, alternativa GeoJSON e visualização no MapLibre;
- importação autenticada de shapefile ZIP com metadados pela interface;
- criação de jobs NDVI com preço, saldo e chave de idempotência;
- acompanhamento de status, progresso e erros por polling;
- cancelamento transacional com liberação idempotente da reserva e auditoria de usuário/data;
- reprocessamento idempotente de jobs terminais, com nova reserva e vínculo ao job de origem;
- galeria com preview privado e downloads autenticados de PNG/PDF;
- saldo, preço vigente e histórico completo do ledger;
- busca, filtros, ordenação e paginação sincronizados com a URL;
- notificações acessíveis, estados de retry, expiração global da sessão e error boundary;
- rotas lazy-loaded, estados vazios/carregamento e layout responsivo;
- testes Vitest/Testing Library para busca, paginação, notificações, cancelamento, reprocessamento e
  operações de geometrias compostas.

### Qualidade e reconciliação

- heartbeat persistido em todas as transições relevantes do pipeline;
- expiração transacional de jobs travados com código `JOB_STALLED` e liberação idempotente;
- auditoria por tenant de produtos sem PNG/PDF e objetos órfãos no storage;
- comando seguro em modo de simulação por padrão e exclusão de órfãos somente com confirmação dupla.

## Estado operacional atual

Ao receber `POST /api/v1/map-jobs/`, o sistema:

1. valida a request e o snapshot da geometria;
2. reserva o custo do índice;
3. cria o job e enfileira o Celery;
4. pesquisa o Copernicus STAC;
5. seleciona e registra a cena;
6. autentica no Sentinel Hub e baixa o GeoTIFF recortado em diretório temporário;
7. valida a grade, aplica SCL/`dataMask` e calcula o NDVI;
8. renderiza o mapa em PNG e PDF;
9. envia somente os produtos finais ao MinIO privado;
10. cria `GeneratedMap`, captura o crédito e conclui o job;
11. remove todos os intermediários.

O último smoke real concluiu o pipeline em uma cena Sentinel-2: criou PNG de 156.848 bytes e PDF de
37.216 bytes, permitiu ambos os downloads autenticados, consumiu exatamente um crédito e deixou zero
reservado. A suíte atual possui 61 testes de backend e 10 testes de frontend aprovados. O frontend
também passa no ESLint e no build TypeScript/Vite, e seus fluxos principais foram validados no
navegador contra a API local.

## Decisão de autenticação Copernicus

A busca STAC permanece como está. Para obter os dados raster foi escolhido o OAuth2 Client
Credentials do Sentinel Hub, criado em:

<https://shapps.dataspace.copernicus.eu/dashboard/#/account/settings>

O `.env` local deverá conter:

```env
COPERNICUS_CLIENT_ID=seu_client_id
COPERNICUS_CLIENT_SECRET=seu_client_secret
COPERNICUS_TOKEN_URL=https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token
COPERNICUS_PROCESS_URL=https://sh.dataspace.copernicus.eu/process/v1
```

Essas variáveis já estão conectadas ao settings e ao ambiente de backend/worker. Não usar
credenciais S3 do CDSE e não confundir essas chaves com `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`. O
secret nunca deve ser enviado ao frontend nem registrado em logs.

## Próxima etapa

Preparar produção e operação contínua:

1. preparar Compose de produção, proxy HTTPS e deploy OCI;
2. agendar a reconciliação por tenant com alertas operacionais;
3. adicionar operações avançadas de divisão e união visual de geometrias.

## Arquivos de referência

- [README.md](README.md): instalação e operação local;
- [docs/architecture.md](docs/architecture.md): arquitetura e multitenancy;
- [docs/properties-api.md](docs/properties-api.md): API de propriedades;
- [docs/map-jobs-billing.md](docs/map-jobs-billing.md): jobs e ledger;
- [docs/stac-processing.md](docs/stac-processing.md): busca STAC e processadores;
- [docs/generated-maps.md](docs/generated-maps.md): renderer, armazenamento e downloads;
- [docs/frontend.md](docs/frontend.md): sessão, rotas e fluxos da interface;
- [docs/reconciliation.md](docs/reconciliation.md): expiração de jobs e auditoria do storage;
- `backend/apps/maps/services/copernicus.py`: seleção de cenas;
- `backend/apps/maps/services/processors/`: contrato e NDVI;
- `backend/apps/maps/services/rendering.py`: composição cartográfica;
- `backend/apps/maps/services/products.py`: persistência e captura;
- `backend/apps/maps/tasks.py`: orquestração atual;
- `backend/apps/billing/services.py`: invariantes financeiros.

## Comandos úteis

```bash
docker compose up --build -d
docker compose exec backend python manage.py setup_dev
docker compose exec backend pytest -q
docker compose exec backend python manage.py check
docker compose exec backend ruff check --no-cache .
docker compose exec frontend npm run build
docker compose exec frontend npm run test
docker compose ps
```
