# API de processamento e créditos

Todos os endpoints exigem JWT válido e membership ativa no tenant resolvido pelo hostname.

## Criar um job

```http
POST /api/v1/map-jobs/
Authorization: Bearer <access-token>
Idempotency-Key: ndvi-fazenda-a-2026-08-01
Content-Type: application/json

{
  "index_type": "NDVI",
  "property_id": "7ecf02d9-48b9-41e5-939c-f0226445e0fb",
  "requested_scene_date": "2026-08-01",
  "max_cloud_cover": "20.00"
}
```

Também é possível enviar `geometry` GeoJSON no lugar de `property_id`. Exatamente uma das duas
origens deve ser informada. Para datas, use `requested_scene_date` ou o par completo
`date_from`/`date_to`, nunca ambos.

A resposta é `202 Accepted`. O header `Idempotent-Replayed` informa se a chave já havia criado o
mesmo job. Repetir a mesma chave e o mesmo payload retorna o recurso original sem nova reserva;
reutilizar a chave com outro payload retorna `409 idempotency_conflict`.

Erros específicos:

- `402 insufficient_credits`: saldo disponível menor que o preço;
- `409 price_not_configured`: não existe preço ativo para o índice;
- `409 idempotency_conflict`: a chave já representa outro payload;
- `503 queue_unavailable`: não foi possível enfileirar; a reserva já foi compensada.

Listagem e detalhe:

```text
GET /api/v1/map-jobs/
GET /api/v1/map-jobs/?status=PENDING&index_type=NDVI
GET /api/v1/map-jobs/{uuid}/
POST /api/v1/map-jobs/{uuid}/cancel/
POST /api/v1/map-jobs/{uuid}/reprocess/
```

`search` consulta nome da propriedade, identificador STAC e etapa atual. `ordering` aceita
`created_at`, `finished_at`, `progress` e `status`. Todas as listagens paginadas aceitam `page` e
`page_size`, limitado a 100.

O cancelamento aceita apenas jobs ativos e é idempotente: sob lock, cria a liberação da reserva,
grava `CANCELLED`, `cancelled_at` e `cancelled_by`. O worker considera `CANCELLED` terminal em todas
as transições. Se cancelamento e finalização concorrerem, o primeiro lock transacional define o
resultado; produtos não são persistidos e créditos liberados não podem ser capturados.

O reprocessamento exige `Idempotency-Key` e aceita jobs `COMPLETED`, `FAILED` ou `CANCELLED`. Ele cria
um novo job com snapshot, datas e parâmetros originais, registra `reprocessed_from_id`, consulta o
preço vigente e faz uma nova reserva. Repetir a mesma chave e origem devolve o mesmo job.

O job guarda um snapshot da geometria. Alterar ou excluir a propriedade depois não muda a área que
será processada.

Cada criação e transição relevante atualiza `heartbeat_at`. O comando `reconcile_maps` usa esse
marcador para detectar inatividade, confirma novamente o estado sob lock e, no modo aplicado, marca
o job como `FAILED/JOB_STALLED` com liberação idempotente da reserva. Consulte
[reconciliation.md](reconciliation.md).

## Consultar billing

```text
GET /api/v1/billing/account/
GET /api/v1/billing/transactions/
GET /api/v1/billing/transactions/?type=RESERVE
GET /api/v1/billing/prices/
```

`CreditAccount` expõe os saldos `available_balance` e `reserved_balance`. O ledger é paginado,
ordenado do evento mais recente para o mais antigo e pode ser filtrado pelo tipo da transação.
Também aceita `ordering` por `created_at`, `amount` ou `transaction_type`.

## Invariantes de crédito

O preço é copiado para `MapJob.credit_cost` no momento da criação, portanto mudanças futuras de
tabela não alteram jobs existentes. As operações usam transação de banco e bloqueio pessimista da
conta:

```text
RESERVE: available -= custo; reserved += custo
CAPTURE: reserved  -= custo
RELEASE: reserved  -= custo; available += custo
```

Cada operação gera uma entrada imutável no ledger e possui chave de idempotência. Um job admite no
máximo uma reserva e apenas um desfecho financeiro: captura ou liberação.

## Estado atual do worker

A task já pesquisa o Copernicus STAC e persiste o `stac_item_id` selecionado. Quando não encontra
uma cena compatível, usa `NO_SATELLITE_SCENE_FOUND`; falhas temporárias do catálogo recebem retry
limitado e terminam como `SATELLITE_CATALOG_UNAVAILABLE` se esgotadas.

Após a seleção, o worker autentica por OAuth2, solicita B04/B08/SCL/`dataMask` recortados na Process
API, valida o GeoTIFF e calcula o NDVI. Os estados avançam por `DOWNLOADING`, `PREPROCESSING` e
`PROCESSING`, `RENDERING` e `UPLOADING`.

O renderer cria PNG/PDF em diretório temporário e o serviço de produto envia ambos ao storage
privado. A criação de `GeneratedMap`, captura do crédito e transição do job para `COMPLETED` ocorrem
na mesma transação de banco. Falhas de configuração, autenticação, serviço raster, renderização,
upload ou finalização recebem códigos específicos e compensam a reserva. Nenhum crédito é capturado
sem os dois produtos persistidos.

## Ajuste administrativo

Créditos manuais não devem ser alterados diretamente no banco ou no admin. Use o comando auditável:

```bash
python manage.py adjust_credits \
  --schema demo \
  --delta 5 \
  --reason 'Crédito de suporte' \
  --idempotency-key support-ticket-123 \
  --username admin
```

`--delta` aceita valor positivo ou negativo, mas nunca zero. A chave permite repetir o comando com
segurança; débitos que tornariam o saldo disponível negativo são recusados.
