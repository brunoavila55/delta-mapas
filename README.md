# Delta Mapas

Base do MVP de um SaaS multitenant para geração de produtos de sensoriamento remoto agrícola. O
projeto sobe Django/GeoDjango, PostgreSQL/PostGIS, Celery, Redis e MinIO, com interface renderizada
por Django Templates + HTMX e autenticação por sessão,
propriedades geoespaciais, cobrança transacional por créditos, criação idempotente de `MapJob` e
seleção de cenas Sentinel-2 via STAC. A interface web oferece login, painel, cadastro de áreas,
acompanhamento de jobs, prévia dos mapas e downloads autenticados. A obtenção do recorte raster e o
cálculo de NDVI usam a Sentinel Hub Process API, autenticada com OAuth2 Client Credentials. O pipeline gera mapas
cartográficos PNG/PDF, persiste somente os produtos finais no MinIO e captura o crédito após a
conclusão.

## Componentes

- Backend: Django 5.2 LTS, GeoDjango e `django-tenants`;
- banco: PostgreSQL 17 + PostGIS 3.5;
- tarefas: Celery com Redis, inicialmente com concorrência 1;
- operação: Celery Beat, reconciliação multi-tenant com lock e alertas JSON/webhook deduplicados;
- arquivos: `django-storages` sobre API S3 do MinIO, bucket privado;
- satélite: Copernicus STAC para descoberta e Sentinel Hub Process API para obtenção dos recortes
  raster;
- cartografia: Matplotlib sobre grade UTM, com coordenadas geográficas transformadas por PyProj;
- interface web: Django Templates, HTMX, CSS e JavaScript progressivo sem etapa de build;
- produção: Gunicorn, WhiteNoise, Caddy como proxy HTTPS e Compose sem portas internas
  publicadas;
- qualidade: pytest, Ruff e Black.

Veja [docs/architecture.md](docs/architecture.md) para as decisões e os limites desta etapa.
O estágio geoespacial atual está em [docs/stac-processing.md](docs/stac-processing.md).
Renderização, persistência e downloads estão em [docs/generated-maps.md](docs/generated-maps.md).
As telas, a sessão e os fluxos do cliente estão em [docs/frontend.md](docs/frontend.md).
Expiração de jobs e auditoria do storage estão em [docs/reconciliation.md](docs/reconciliation.md).
O deploy de produção na Oracle Cloud está em [docs/deployment-oci.md](docs/deployment-oci.md).
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
│   ├── Dockerfile.prod
│   └── manage.py
├── docs/
│   ├── architecture.md
│   ├── deployment-oci.md
│   └── stac-processing.md
├── ops/
│   ├── backup/
│   ├── caddy/
│   └── systemd/
├── .env.example
├── .env.prod.example
├── context.md
├── docker-compose.yml
└── docker-compose.prod.yml
```

## Pré-requisitos

- Docker Desktop/Engine com Docker Compose v2;
- portas locais 8000 e 9001 livres.

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

O `.env` está ignorado pelo Git. Nunca exponha o client secret no navegador, em logs ou em arquivos
versionados. Backend e worker são os únicos consumidores. Depois de adicionar ou alterar as
credenciais, recrie esses serviços para aplicar o ambiente:

```bash
docker compose up --build -d backend celery_worker
```

O token é obtido pelo fluxo Client Credentials, mantido somente em memória e renovado antes da
expiração. Consulte `.env.example` para timeouts, retries, resolução e limites de segurança.

## Produção

O ambiente de produção usa imagens sem bind mount, Gunicorn, arquivos estáticos comprimidos pelo
WhiteNoise e Caddy como único serviço público. PostgreSQL, Redis, MinIO e Django não publicam portas
no host. O Caddy termina HTTPS e encaminha toda a aplicação Django na mesma origem.

Copie `.env.prod.example` para `.env.prod`, preencha os segredos e valide antes de iniciar:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.prod -f docker-compose.prod.yml build --pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

Os serviços one-shot aplicam migrations, criam o bucket privado e provisionam o primeiro tenant de
forma idempotente. Requisitos de DNS, rede OCI, backup, atualização e checklist de liberação estão no
[runbook de deploy](docs/deployment-oci.md).

O usuário criado por `provision_tenant` é proprietário somente do tenant e não recebe `is_staff` ou
`is_superuser`. Crie um operador global separado com `createsuperuser` apenas quando o Django Admin
for realmente necessário.

Para criar localmente um snapshot autenticado de PostgreSQL e MinIO em `backups/`, configure
`BACKUP_SIGNING_KEY` e `BACKUP_ENVIRONMENT` e execute:

```bash
docker compose --profile ops run --rm backup
```

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
| Interface web | http://localhost:8000/ |
| Health check | http://localhost:8000/health/ |
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

## Fluxo de processamento

A criação de um job pela interface reserva o preço vigente do índice. O worker pesquisa a melhor
cena, obtém um GeoTIFF temporário com B04, B08, SCL e
`dataMask`, aplica as máscaras, calcula o NDVI, renderiza PNG/PDF e envia os arquivos finais ao
MinIO. `GeneratedMap`, conclusão do job e captura do crédito são finalizados transacionalmente. Em
qualquer falha anterior, os temporários são removidos e a reserva é liberada.

O cancelamento devolve a reserva somente enquanto o job está pendente ou procurando uma cena. A
partir de `DOWNLOADING`, o crédito é capturado porque a solicitação paga ao provedor já começou.

## Controles de segurança do MVP

- produção recusa `DJANGO_SECRET_KEY` ausente, curta ou igual à chave insegura de desenvolvimento;
- login é limitado por IP e por conta/tenant, com contadores compartilhados no Redis;
- geometrias e shapefiles têm limites de coordenadas, componentes, profundidade e feições antes de
  operações GEOS/Shapely custosas;
- OAuth e Process API exigem HTTPS, não seguem redirects e aplicam limites de resposta; o transporte
  STAC também limita cada página e o total recebido;
- snapshots incluem HMAC do arquivo de checksums e vínculo ao ambiente de origem antes de qualquer
  restauração destrutiva.

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

Em produção, `celery_beat` agenda a mesma reconciliação para todos os tenants a cada 15 minutos por
padrão. Um advisory lock impede execuções sobrepostas, jobs travados são expirados automaticamente e
órfãos não são excluídos. Anomalias sempre aparecem nos logs JSON e podem ser enviadas a um webhook
HTTPS assinado e deduplicado. Consulte [docs/reconciliation.md](docs/reconciliation.md) para as
variáveis e o contrato do alerta.

## Verificações

```bash
docker compose run --rm backend python manage.py check
docker compose run --rm backend pytest
docker compose run --rm backend ruff check --no-cache .
docker compose config --quiet
docker compose --env-file .env.prod -f docker-compose.prod.yml config --quiet
```

Para verificar o worker:

```bash
docker compose exec backend python manage.py shell -c \
  "from apps.maps.tasks import healthcheck; print(healthcheck.delay().get(timeout=10))"
```

## Limitações deliberadas desta etapa

- o raster Sentinel é temporário e removido após o job; somente produtos finais são armazenados;
- o template cartográfico atual é fixo em A4 paisagem e ainda não possui mapas-base externos;
- produtos com arquivo ausente são reportados para intervenção, sem recomposição automática;
- o deploy atual concentra aplicação, banco, fila e storage em uma única VM; alta disponibilidade e
  storage externo ficam para uma etapa futura.

## Próximo passo

Concluir a implantação real na OCI, copiar os snapshots para storage externo e validar o fluxo ponta
a ponta, os timers e o monitoramento no domínio público.
