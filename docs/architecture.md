# Arquitetura do Delta Mapas

## Escopo atual

O projeto possui a fundação executável do MVP, autenticação JWT, API de propriedades com GeoJSON e
importação segura de shapefile, cobrança transacional, API idempotente de `MapJob` e seleção de cenas
no Copernicus STAC. Download, recorte raster, máscaras e cálculo vetorizado de NDVI estão integrados;
renderização cartográfica, persistência privada e captura de créditos também estão operacionais.

## Visão geral

```text
React + Vite
      ↓ HTTP /api/v1
Django REST Framework
      ↓
PostgreSQL + PostGIS

Django ──enfileira──→ Celery ──broker/resultados──→ Redis
                           │
                           ├── Copernicus STAC
                           ├── Sentinel Hub Process API (OAuth2)
                           └── produtos finais ──→ MinIO (S3)
```

O frontend usa TanStack Query para estado de servidor, React Router para navegação e MapLibre para
os fluxos cartográficos futuros. O backend expõe OpenAPI por `drf-spectacular`. Arquivos finais usam
a abstração `STORAGES` do Django; nenhum código de domínio depende diretamente do SDK do MinIO.

## Multitenancy

`django-tenants` seleciona o schema PostgreSQL a partir do hostname. O middleware de tenant é o
primeiro da cadeia para que toda consulta posterior use o `search_path` correto.

### Schema `public`

- `Tenant` e `Domain`;
- `User` e `Membership`;
- blacklist e rastreamento de refresh tokens JWT;
- autenticação, sessões e administração;
- metadados globais da plataforma.

Um usuário é global e pode possuir memberships em várias organizações. A role pertence ao vínculo,
e não ao usuário.

### Schema de cada tenant

- `Property`;
- `MapJob` e `GeneratedMap`;
- `CreditAccount`, `CreditTransaction` e `ProcessingPrice`.

O isolamento primário acontece no banco: tabelas operacionais de organizações diferentes residem em
schemas diferentes. Views futuras ainda devem filtrar por autorização/membership e responder `404`
para UUIDs externos ao tenant atual.

## Decisões iniciais

1. **Django 5.2 LTS e Python 3.12.** Mantêm uma janela de suporte longa sem adotar versões de Python
   muito recentes para o ecossistema geoespacial.
2. **Usuários no schema público.** Permite que a mesma pessoa participe de várias organizações sem
   duplicar identidade e credenciais.
3. **Billing operacional no tenant.** Conta e ledger acompanham o isolamento do restante dos dados
   da organização. Integrações e webhooks globais poderão viver no schema público quando surgirem.
4. **Saldo materializado mais ledger imutável.** Os saldos permitem leitura rápida; cada mutação gera
   `CreditTransaction` idempotente e transacional. Reserva, captura e liberação bloqueiam a conta com
   `SELECT FOR UPDATE`, preservando os invariantes sob concorrência.
5. **EPSG:6933 para área inicial.** A geometria salva permanece em EPSG:4326, mas a área é calculada
   numa projeção equal-area em metros, nunca diretamente em graus.
6. **Objetos privados.** O bucket não aceita acesso anônimo e o storage gera URLs assinadas.
7. **Worker com concorrência 1.** Evita que rasterizações concorrentes esgotem a memória do alvo OCI
   Ampere A1; o valor poderá ser ajustado por métricas.

## Fluxo de geração

```text
Request validada
      ↓
Reserva idempotente de crédito + MapJob
      ↓
Celery pesquisa Sentinel-2 L2A no STAC
      ↓
TemporaryDirectory: B04 + B08 + SCL → crop → máscara → NDVI
      ↓
Renderer gera PNG/PDF
      ↓
Produtos finais privados no storage S3
      ↓
GeneratedMap + captura do crédito
      ↓
Limpeza garantida dos intermediários
```

Criação, reserva, pesquisa STAC e cálculo NDVI já estão implementados. A seleção filtra interseção,
período, cobertura máxima de nuvens e assets obrigatórios, priorizando menor nuvem e cena mais
recente. A Process API devolve um GeoTIFF temporário numa grade UTM comum; Rasterio valida as bandas
e o processador aplica `dataMask`, SCL e nodata. Matplotlib compõe PNG/PDF; somente esses produtos
são enviados ao MinIO. A task cria `GeneratedMap`, captura o crédito e conclui o job.

STAC, OAuth, Process API, processamento NumPy/Rasterio, renderização e persistência são serviços
separados.
`BaseIndexProcessor` e `NDVIProcessor` calculam o índice sobre arrays alinhados e aplicam
SCL/nodata sem loops por pixel. A task orquestra o pipeline, preservando idempotência e controle
explícito de estado. A captura é feita somente depois da persistência de `GeneratedMap`; falhas
anteriores liberam a reserva.
