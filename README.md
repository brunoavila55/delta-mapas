# Delta Mapas

Base do MVP de um SaaS multitenant para geração de produtos de sensoriamento remoto agrícola. O
projeto sobe Django/GeoDjango, PostgreSQL/PostGIS, Celery, Redis, MinIO e React, com autenticação JWT,
propriedades geoespaciais, cobrança transacional por créditos, criação idempotente de `MapJob` e
seleção de cenas Sentinel-2 via STAC. O frontend já oferece login, painel, cadastro de áreas,
acompanhamento de jobs, prévia dos mapas e downloads autenticados. A obtenção do recorte raster e o
cálculo de NDVI usam a Sentinel Hub Process API, autenticada com OAuth2 Client Credentials. O pipeline gera mapas
cartográficos PNG/PDF, persiste somente os produtos finais no MinIO e captura o crédito após a
conclusão.

## Componentes

- Backend: Django 5.2 LTS, Django REST Framework, GeoDjango e `django-tenants`;
- banco: PostgreSQL 17 + PostGIS 3.5;
- tarefas: Celery com Redis, inicialmente com concorrência 1;
- arquivos: `django-storages` sobre API S3 do MinIO, bucket privado;
- satélite: Copernicus STAC para descoberta e Sentinel Hub Process API para obtenção dos recortes
  raster;
- cartografia: Matplotlib sobre grade UTM, com coordenadas geográficas transformadas por PyProj;
- API: OpenAPI/Swagger com `drf-spectacular`;
- frontend: React, Vite, TypeScript, Tailwind, MapLibre, TanStack Query e React Router;
- qualidade: pytest, Ruff e Black.

Veja [docs/architecture.md](docs/architecture.md) para as decisões e os limites desta etapa.
Os contratos da API estão em [docs/properties-api.md](docs/properties-api.md) e
[docs/map-jobs-billing.md](docs/map-jobs-billing.md).
O estágio geoespacial atual está em [docs/stac-processing.md](docs/stac-processing.md).
Renderização, persistência e downloads estão em [docs/generated-maps.md](docs/generated-maps.md).
As telas, a sessão e os fluxos do cliente estão em [docs/frontend.md](docs/frontend.md).
Expiração de jobs e auditoria do storage estão em [docs/reconciliation.md](docs/reconciliation.md).
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

A pesquisa no STAC não exige autenticação. Para processar os recortes raster, crie um OAuth client em
[Copernicus Data Space — User Settings](https://shapps.dataspace.copernicus.eu/dashboard/#/account/settings)
e adicione os valores somente ao `.env` local da raiz:

```env
COPERNICUS_CLIENT_ID=seu_client_id
COPERNICUS_CLIENT_SECRET=seu_client_secret
COPERNICUS_TOKEN_URL=https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token
COPERNICUS_PROCESS_URL=https://sh.dataspace.copernicus.eu/process/v1
```

O `.env` está ignorado pelo Git. Nunca exponha o client secret no React, em logs ou em arquivos
versionados. Backend e worker são os únicos consumidores. Depois de adicionar ou alterar as
credenciais, recrie esses serviços para aplicar o ambiente:

```bash
docker compose up --build -d backend celery_worker
```

O token é obtido pelo fluxo Client Credentials, mantido somente em memória e renovado antes da
expiração. Consulte `.env.example` para timeouts, retries, resolução e limites de segurança.

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
POST /api/v1/map-jobs/{uuid}/cancel/
POST /api/v1/map-jobs/{uuid}/reprocess/

GET /api/v1/maps/
GET /api/v1/maps/{uuid}/
GET /api/v1/maps/{uuid}/download/png/
GET /api/v1/maps/{uuid}/download/pdf/
```

A criação de job exige o header `Idempotency-Key`, reserva o preço vigente do índice e responde
`202 Accepted`. O worker pesquisa a melhor cena, obtém um GeoTIFF temporário com B04, B08, SCL e
`dataMask`, aplica as máscaras, calcula o NDVI, renderiza PNG/PDF e envia os arquivos finais ao
MinIO. `GeneratedMap`, conclusão do job e captura do crédito são finalizados transacionalmente. Em
qualquer falha anterior, os temporários são removidos e a reserva é liberada.

Para ajustar créditos manualmente com ledger auditável:

```bash
docker compose exec backend python manage.py adjust_credits \
  --schema demo \
  --delta 5 \
  --reason 'Crédito de suporte' \
  --idempotency-key support-ticket-123 \
  --username admin
```

Para auditar jobs travados e arquivos do tenant sem modificar dados:

```bash
docker compose exec backend python manage.py reconcile_maps --schema demo
```

Use `--apply` para expirar jobs travados e devolver suas reservas. A exclusão de objetos órfãos
exige as duas opções `--apply --delete-orphans`; produtos com arquivo ausente são apenas reportados.

## Verificações

```bash
docker compose run --rm backend python manage.py check
docker compose run --rm backend pytest
docker compose run --rm backend ruff check .
docker compose run --rm frontend npm run build
docker compose run --rm frontend npm run lint
docker compose run --rm frontend npm run test
docker compose config --quiet
```

Para verificar o worker:

```bash
docker compose exec backend python manage.py shell -c \
  "from apps.maps.tasks import healthcheck; print(healthcheck.delay().get(timeout=10))"
```

## Limitações deliberadas desta etapa

- geometrias compostas podem ser desenhadas e editadas no mapa, mas ainda não há operações
  avançadas como divisão ou união visual de componentes;
- o raster Sentinel é temporário e removido após o job; somente produtos finais são armazenados;
- o template cartográfico atual é fixo em A4 paisagem e ainda não possui mapas-base externos;
- a reconciliação existe como comando operacional, mas ainda não possui agendamento recorrente;
- produtos com arquivo ausente são reportados para intervenção, sem recomposição automática;
- `docker-compose.prod.yml`, proxy HTTPS e deploy OCI ficam para a etapa de produção.

## Próximo passo

Preparar o Compose de produção com proxy HTTPS, serviços endurecidos e deploy OCI.
