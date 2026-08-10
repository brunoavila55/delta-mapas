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
```

O job guarda um snapshot da geometria. Alterar ou excluir a propriedade depois não muda a área que
será processada.

## Consultar billing

```text
GET /api/v1/billing/account/
GET /api/v1/billing/transactions/
GET /api/v1/billing/transactions/?type=RESERVE
GET /api/v1/billing/prices/
```

`CreditAccount` expõe os saldos `available_balance` e `reserved_balance`. O ledger é paginado,
ordenado do evento mais recente para o mais antigo e pode ser filtrado pelo tipo da transação.

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

## Estado provisório do worker

A task já pesquisa o Copernicus STAC e persiste o `stac_item_id` selecionado. Quando não encontra
uma cena compatível, usa `NO_SATELLITE_SCENE_FOUND`; falhas temporárias do catálogo recebem retry
limitado e terminam como `SATELLITE_CATALOG_UNAVAILABLE` se esgotadas.

Como download e recorte ainda são a próxima etapa, após uma seleção bem-sucedida o job termina como
`FAILED` com `error_code=PIPELINE_NOT_IMPLEMENTED` e libera a reserva. Assim, API, fila e busca real
podem ser exercitadas sem cobrar por um produto inexistente.

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
