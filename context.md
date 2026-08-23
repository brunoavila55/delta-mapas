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
Django Templates + HTMX
      ↓ sessão, views e partials
Django + GeoDjango
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

- Django 5.2, GeoDjango e `django-tenants`;
- PostgreSQL/PostGIS;
- Celery com concorrência 1 e Redis;
- MinIO privado por meio de `django-storages`;
- Django Templates, HTMX, CSS e JavaScript progressivo;
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

- stack Docker com backend, worker, PostgreSQL/PostGIS, Redis e MinIO;
- healthchecks, logging estruturado e seed `setup_dev`;
- compatibilidade das dependências novas confirmada para Linux ARM64.

### Autenticação e propriedades

- login e logout por sessão Django;
- membership ativa por tenant;
- cadastro, edição e exclusão de propriedades por formulários Django;
- normalização para `MultiPolygon` em EPSG:4326;
- área calculada no backend em projeção equal-area;
- importação segura de shapefile ZIP usando diretório temporário.

### Billing e jobs

- conta com saldos disponível e reservado;
- ledger imutável e idempotente;
- preço configurável por índice;
- reserva, captura e liberação transacionais com locks;
- criação de `MapJob` pela interface com idempotência no serviço de domínio;
- listagem e acompanhamento de jobs por HTMX;
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
- persistência privada de PNG/PDF no MinIO e downloads autenticados por sessão;
- criação idempotente de `GeneratedMap`, conclusão do job e captura transacional do crédito.

### Interface web operacional

- autenticação por sessão Django, CSRF e membership ativa por tenant;
- painel com créditos, área monitorada, jobs ativos e produtos recentes;
- cadastro e edição de propriedades por shapefile ZIP ou GeoJSON;
- criação de jobs NDVI com preço, saldo e janela de observação;
- acompanhamento de status, progresso e erros por partial HTMX com atualização automática;
- cancelamento e reprocessamento protegidos por role e confirmação;
- biblioteca com preview e downloads privados de PNG/PDF;
- saldo, preço vigente e histórico completo do ledger;
- busca, filtros, ordenação e paginação sincronizados com a URL;
- estados vazios, mensagens acessíveis e layout responsivo;
- nenhuma etapa de build, bundle Node, React ou TypeScript.

### Qualidade e reconciliação

- heartbeat persistido em todas as transições relevantes do pipeline;
- expiração transacional de jobs travados com código `JOB_STALLED` e liberação idempotente;
- auditoria por tenant de produtos sem PNG/PDF e objetos órfãos no storage;
- comando seguro em modo de simulação por padrão e exclusão de órfãos somente com confirmação dupla.
- Celery Beat com intervalo configurável e uma task global de reconciliação;
- advisory lock PostgreSQL para impedir execuções sobrepostas;
- expiração automática de jobs travados em produção, mantendo exclusão de órfãos desabilitada;
- resumo estruturado nos logs e webhook HTTPS opcional com HMAC-SHA256;
- deduplicação de incidentes no Redis com cooldown e nova tentativa após falha de entrega.

### Produção e deploy

- imagens de produção imutáveis, sem bind mount de código ou dependências de desenvolvimento;
- Gunicorn para Django e WhiteNoise para arquivos estáticos comprimidos e versionados;
- Django Templates + HTMX servidos pelo backend e Caddy como proxy reverso com HTTPS automático;
- somente TCP 80/443 e UDP 443 publicados; PostgreSQL, Redis, MinIO e Django ficam internos;
- cookies seguros, redirecionamento HTTPS, proxy confiável e HSTS configuráveis por ambiente;
- migrations, bucket MinIO e primeiro tenant executados por serviços one-shot idempotentes;
- bootstrap `provision_tenant` sem senha na linha de comando, sem redefini-la em novos deploys e sem
  conceder `is_staff`/`is_superuser` ao proprietário do tenant;
- logs com rotação, containers da aplicação somente leitura e privilégios Linux reduzidos;
- runbook de OCI com DNS, NSG, deploy, atualização, backup e checklist de liberação.
- imagem operacional com `pg_dump`/`pg_restore` e MinIO Client para snapshots atômicos do banco e
  bucket, checksums SHA-256 autenticados por HMAC, vínculo ao ambiente, retenção e restauração
  protegida por confirmação explícita;
- timer systemd diário e ensaio real de restauração aprovado em projeto Compose isolado.

## Estado operacional atual

Ao receber uma solicitação válida em `/jobs/new/`, o sistema:

1. valida o formulário e o snapshot da geometria;
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
reservado. A interface atual é server-side, usa sessão Django, CSRF e partials HTMX e não possui
toolchain Node/TypeScript.

Para produção, `docker-compose.prod.yml` agora encadeia PostgreSQL, migrations, provisionamento,
MinIO, backend, worker e Caddy por healthchecks. A implantação real na OCI ainda precisa ser feita e
validada no host arm64 seguindo `docs/deployment-oci.md`.

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
secret nunca deve ser enviado ao navegador nem registrado em logs.

## Próxima etapa

Preparar produção e operação contínua:

1. realizar o deploy real na OCI e validar DNS, HTTPS, timer de backup e alertas externos;
2. validar união/recorte e o pipeline Copernicus ponta a ponta no domínio público;
3. sincronizar snapshots para storage externo criptografado e evoluir observabilidade e, quando
   necessário, serviços gerenciados/alta disponibilidade.

## Auditoria de segurança concluída

Em 17/08/2026, as nove falhas validadas na auditoria do repositório foram corrigidas: separação entre
proprietário do tenant e administrador global, chave Django obrigatória em produção, throttling de
login, limites de complexidade geoespacial, política econômica segura no cancelamento, HTTPS e
redirects bloqueados nas chamadas autenticadas do Copernicus, respostas OAuth/STAC limitadas e
backups autenticados por HMAC com vínculo ao ambiente. A etapa atual é repetir os testes ponta a
ponta no domínio de produção e manter esses controles nas próximas mudanças.

## Arquivos de referência

- [README.md](README.md): instalação e operação local;
- [docs/architecture.md](docs/architecture.md): arquitetura e multitenancy;
- [docs/stac-processing.md](docs/stac-processing.md): busca STAC e processadores;
- [docs/generated-maps.md](docs/generated-maps.md): renderer, armazenamento e downloads;
- [docs/frontend.md](docs/frontend.md): sessão, rotas e fluxos da interface;
- [docs/reconciliation.md](docs/reconciliation.md): expiração de jobs e auditoria do storage;
- [docs/deployment-oci.md](docs/deployment-oci.md): produção, HTTPS, OCI, backup e atualização;
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
docker compose --env-file .env.prod -f docker-compose.prod.yml config --quiet
docker compose ps
```
