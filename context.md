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
                           ├── próxima etapa: Sentinel Hub Process API via OAuth2
                           └── MinIO: somente PNG/PDF finais
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
- `BaseIndexProcessor` extensível;
- `NDVIProcessor` vetorizado com máscara SCL, nodata, NaN e divisão por zero.

## Estado operacional atual

Ao receber `POST /api/v1/map-jobs/`, o sistema:

1. valida a request e o snapshot da geometria;
2. reserva o custo do índice;
3. cria o job e enfileira o Celery;
4. pesquisa o Copernicus STAC;
5. seleciona e registra a cena;
6. encerra com `PIPELINE_NOT_IMPLEMENTED`;
7. libera integralmente o crédito.

Esse encerramento é deliberado: ainda não existe produto final, portanto nenhum crédito pode ser
capturado. O último smoke real selecionou uma cena Sentinel-2, preservou 10 créditos disponíveis e
deixou zero reservado. A suíte atual possui 34 testes aprovados.

## Decisão de autenticação Copernicus

A busca STAC permanece como está. Para obter os dados raster foi escolhido o OAuth2 Client
Credentials do Sentinel Hub, criado em:

<https://shapps.dataspace.copernicus.eu/dashboard/#/account/settings>

O `.env` local deverá conter:

```env
COPERNICUS_CLIENT_ID=seu_client_id
COPERNICUS_CLIENT_SECRET=seu_client_secret
COPERNICUS_TOKEN_URL=https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token
COPERNICUS_PROCESS_URL=https://sh.dataspace.copernicus.eu/api/v1/process
```

Essas variáveis ainda não estão conectadas ao código. Não usar credenciais S3 do CDSE e não
confundir essas chaves com `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`. O secret nunca deve ser enviado ao
frontend nem registrado em logs.

## Próxima etapa

Implementar a obtenção dos rasters pela Sentinel Hub Process API:

1. adicionar as variáveis OAuth ao settings e ao ambiente do backend/worker;
2. criar cliente de token Client Credentials com timeout, cache e renovação antes da expiração;
3. criar cliente da Process API atrás de uma abstração própria;
4. solicitar B04, B08 e SCL limitados à AOI e ao contexto da cena selecionada;
5. manter qualquer resposta raster em `TemporaryDirectory`;
6. alinhar/reprojetar as bandas quando necessário;
7. alimentar `NDVIProcessor` e atualizar os estados do job;
8. em falha, limpar temporários e liberar o crédito de forma idempotente.

Renderização cartográfica, upload de PNG/PDF, criação de `GeneratedMap` e captura do crédito ficam
para a etapa seguinte.

## Arquivos de referência

- [README.md](README.md): instalação e operação local;
- [docs/architecture.md](docs/architecture.md): arquitetura e multitenancy;
- [docs/properties-api.md](docs/properties-api.md): API de propriedades;
- [docs/map-jobs-billing.md](docs/map-jobs-billing.md): jobs e ledger;
- [docs/stac-processing.md](docs/stac-processing.md): busca STAC e processadores;
- `backend/apps/maps/services/copernicus.py`: seleção de cenas;
- `backend/apps/maps/services/processors/`: contrato e NDVI;
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
docker compose ps
```
