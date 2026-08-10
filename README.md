# Delta Mapas

Base do MVP de um SaaS multitenant para geração de produtos de sensoriamento remoto agrícola. O
projeto sobe Django/GeoDjango, PostgreSQL/PostGIS, Celery, Redis, MinIO e React, com autenticação JWT,
propriedades geoespaciais, cobrança transacional por créditos, criação idempotente de `MapJob` e
seleção de cenas Sentinel-2 via STAC. O download e o pipeline raster completo ainda não foram
implementados. A próxima integração obterá os dados pela Sentinel Hub Process API, autenticada com
OAuth2 Client Credentials.

## Componentes

- Backend: Django 5.2 LTS, Django REST Framework, GeoDjango e `django-tenants`;
- banco: PostgreSQL 17 + PostGIS 3.5;
- tarefas: Celery com Redis, inicialmente com concorrência 1;
- arquivos: `django-storages` sobre API S3 do MinIO, bucket privado;
- satélite: Copernicus STAC para descoberta e Sentinel Hub Process API para obtenção futura dos
  recortes raster;
- API: OpenAPI/Swagger com `drf-spectacular`;
- frontend: React, Vite, TypeScript, Tailwind, MapLibre, TanStack Query e React Router;
- qualidade: pytest, Ruff e Black.

Veja [docs/architecture.md](docs/architecture.md) para as decisões e os limites desta etapa.
Os contratos da API estão em [docs/properties-api.md](docs/properties-api.md) e
[docs/map-jobs-billing.md](docs/map-jobs-billing.md).
O estágio geoespacial atual está em [docs/stac-processing.md](docs/stac-processing.md).
O contexto consolidado para retomada do desenvolvimento está em [context.md](context.md).

## Estrutura

```text
.
├── backend/
│   ├── apps/
│   │   ├── accounts/
│   │   ├── billing/
│   │   ├── maps/
│   │   ├── properties/
│   │   └── tenants/
│   ├── delta_maps/
│   ├── requirements/
│   ├── Dockerfile
│   └── manage.py
├── docs/
│   ├── architecture.md
│   ├── map-jobs-billing.md
│   ├── properties-api.md
│   └── stac-processing.md
├── frontend/
│   ├── src/
│   ├── Dockerfile
│   └── package.json
├── .env.example
├── context.md
└── docker-compose.yml
```

## Pré-requisitos

- Docker Desktop/Engine com Docker Compose v2;
- portas locais 5173, 8000 e 9001 livres.

As imagens escolhidas são publicadas para arquiteturas usuais de contêiner, visando desenvolvimento
em amd64 e implantação arm64. Valide todos os artefatos na máquina OCI antes do deploy de produção.

## Início rápido

Opcionalmente copie `.env.example` para `.env` e troque todos os valores marcados como `change-me`.
Os defaults do Compose permitem um primeiro boot local sem o arquivo, mas nunca devem ser usados em
produção.

```bash
docker compose up --build
```

Em outro terminal, crie o tenant local, domínio, superusuário e dez créditos iniciais:

```bash
docker compose exec \
  -e DEV_SUPERUSER_PASSWORD='escolha-uma-senha-local' \
  backend python manage.py setup_dev
```

O comando é idempotente: pode ser repetido sem duplicar o bônus inicial. Depois do seed, `localhost`
resolve o tenant `demo` e `public.localhost` resolve o schema público. Em alguns sistemas pode ser
necessário adicionar `127.0.0.1 public.localhost` ao arquivo de hosts.

## Credenciais Copernicus OAuth

A pesquisa no STAC atual não exige autenticação. Para a próxima etapa, crie um OAuth client em
[Copernicus Data Space — User Settings](https://shapps.dataspace.copernicus.eu/dashboard/#/account/settings)
e adicione os valores somente ao `.env` local da raiz:

```env
COPERNICUS_CLIENT_ID=seu_client_id
COPERNICUS_CLIENT_SECRET=seu_client_secret
COPERNICUS_TOKEN_URL=https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token
COPERNICUS_PROCESS_URL=https://sh.dataspace.copernicus.eu/api/v1/process
```

O `.env` está ignorado pelo Git. Nunca exponha o client secret no React, em logs ou em arquivos
versionados. Backend e worker serão os únicos consumidores. Estas quatro variáveis documentam o
contrato decidido, mas ainda serão conectadas ao Django/Compose na próxima etapa do pipeline.

## Migrations

O backend executa migrations compartilhadas ao iniciar. Durante o desenvolvimento:

```bash
# Gerar migrations após alterar models
docker compose run --rm backend python manage.py makemigrations

# Aplicar somente apps compartilhados ao schema public
docker compose run --rm backend python manage.py migrate_schemas --shared

# Aplicar apps de tenant a todos os tenants existentes
docker compose run --rm backend python manage.py migrate_schemas --tenant
```

Criar um superusuário manualmente, se o seed não for desejado:

```bash
docker compose exec backend python manage.py createsuperuser
```

## URLs locais

| Serviço | URL |
| --- | --- |
| Frontend | http://localhost:5173 |
| API health | http://localhost:8000/api/v1/health/ |
| Swagger | http://localhost:8000/api/docs/ |
| ReDoc | http://localhost:8000/api/redoc/ |
| OpenAPI | http://localhost:8000/api/schema/ |
| Django admin | http://localhost:8000/admin/ |
| MinIO Console | http://localhost:9001 |

As credenciais do MinIO vêm de `MINIO_ACCESS_KEY` e `MINIO_SECRET_KEY`. A API interna do MinIO não é
publicada no host; backend e worker acessam `minio:9000` pela rede do Compose.

## Models iniciais

- `Tenant` e `Domain`: organização, schema e hostname;
- `User` e `Membership`: identidade global e participação multi-organização com role;
- `Property`: geometria `MultiPolygon` em EPSG:4326 e área recalculada no backend;
- `MapJob`: snapshot da geometria, status explícito, progresso e rastreabilidade Celery/STAC;
- `GeneratedMap`: produto concluído, metadados e arquivos privados PNG/PDF;
- `CreditAccount`: saldos disponível e reservado materializados por tenant;
- `CreditTransaction`: ledger idempotente e auditável, opcionalmente associado a um job.

Os models de domínio usam UUID como chave pública. `MapJob` e `GeneratedMap` são separados para não
misturar estado transitório com um produto concluído.

## API atual

```text
POST /api/v1/auth/login/
POST /api/v1/auth/refresh/
POST /api/v1/auth/logout/
GET  /api/v1/auth/me/

GET    /api/v1/properties/
POST   /api/v1/properties/
GET    /api/v1/properties/{uuid}/
PATCH  /api/v1/properties/{uuid}/
DELETE /api/v1/properties/{uuid}/
POST   /api/v1/properties/import/

GET  /api/v1/billing/account/
GET  /api/v1/billing/transactions/
GET  /api/v1/billing/prices/

GET  /api/v1/map-jobs/
POST /api/v1/map-jobs/
GET  /api/v1/map-jobs/{uuid}/
```

A criação de job exige o header `Idempotency-Key`, reserva o preço vigente do índice e responde
`202 Accepted`. O worker pesquisa e registra a melhor cena disponível. Enquanto download e
processamento raster não existem, encerra o job com `PIPELINE_NOT_IMPLEMENTED` e libera integralmente
a reserva, sem consumir créditos.

Para ajustar créditos manualmente com ledger auditável:

```bash
docker compose exec backend python manage.py adjust_credits \
  --schema demo \
  --delta 5 \
  --reason 'Crédito de suporte' \
  --idempotency-key support-ticket-123 \
  --username admin
```

## Verificações

```bash
docker compose run --rm backend python manage.py check
docker compose run --rm backend pytest
docker compose run --rm backend ruff check .
docker compose run --rm frontend npm run build
docker compose config --quiet
```

Para verificar o worker:

```bash
docker compose exec backend python manage.py shell -c \
  "from apps.maps.tasks import healthcheck; print(healthcheck.delay().get(timeout=10))"
```

## Limitações deliberadas desta etapa

- as telas React ainda não consomem autenticação, propriedades, billing e jobs;
- assets Copernicus ainda não são baixados; nenhuma imagem bruta é armazenada;
- autenticação OAuth e chamada à Sentinel Hub Process API ainda não estão conectadas;
- o processador NDVI opera sobre arrays já alinhados, mas ainda não está conectado à task;
- o worker encerra os jobs após selecionar a cena e libera a reserva até o pipeline avançar;
- `docker-compose.prod.yml`, proxy HTTPS e deploy OCI ficam para a etapa de produção.

## Próximo passo

Implementar o cliente OAuth2 com cache seguro do token e integrar a Sentinel Hub Process API para
obter B04, B08 e SCL recortados na AOI. Os resultados temporários serão alinhados com Rasterio e
entregues ao processador NDVI; nenhum raster Sentinel bruto será persistido no MinIO.
