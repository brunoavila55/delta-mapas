# Reconciliação operacional

O comando `reconcile_maps` audita um tenant por execução. Sem opções de aplicação ele é somente
leitura: lista jobs ativos sem atividade, arquivos referenciados que não existem e objetos no
prefixo privado do tenant que não possuem referência em `GeneratedMap`.

```bash
docker compose exec backend python manage.py reconcile_maps --schema demo
```

O limite padrão é 120 minutos e pode ser configurado por `MAP_JOB_STALE_MINUTES` ou substituído na
execução:

```bash
docker compose exec backend python manage.py reconcile_maps \
  --schema demo \
  --stale-minutes 180
```

## Aplicar expiração

```bash
docker compose exec backend python manage.py reconcile_maps \
  --schema demo \
  --apply
```

Para cada candidato, o serviço abre uma transação, bloqueia o job e verifica novamente status e
última atividade. Se ele continuar travado, libera a reserva de forma idempotente e grava
`FAILED`, `JOB_STALLED`, `finished_at` e um novo heartbeat. Se o worker voltar depois disso, encontra
um estado terminal e não persiste produto nem captura crédito.

## Auditoria do storage

O comando verifica `png_file` e `pdf_file` de todos os produtos do tenant e percorre somente
`tenants/{tenant_id}/maps/`. As categorias são:

- `AUSENTE`: o banco referencia um arquivo inexistente; o registro e o ledger são preservados para
  análise e possível recomposição;
- `ÓRFÃO`: o arquivo está no prefixo do tenant, mas nenhum produto o referencia;
- `EXCLUÍDO`: um órfão removido durante uma execução explicitamente destrutiva.

A exclusão de órfãos requer confirmação por duas opções:

```bash
docker compose exec backend python manage.py reconcile_maps \
  --schema demo \
  --apply \
  --delete-orphans
```

Execute primeiro sem `--apply`, revise a lista e só então habilite a exclusão. Objetos referenciados
nunca são removidos pela rotina, mesmo quando o outro arquivo do mesmo produto está ausente.

## Agendamento

O serviço `celery_beat` publica `maps.reconcile_all_tenants` no intervalo configurado. A task obtém
um advisory lock global no PostgreSQL, lista os tenants no schema público e executa cada tenant de
forma isolada. Se uma execução anterior ainda estiver ativa, a nova execução termina como
`skipped_locked` sem duplicar trabalho.

Em desenvolvimento o agendamento vem desabilitado. Em produção os defaults são:

```env
MAP_RECONCILIATION_ENABLED=true
MAP_RECONCILIATION_INTERVAL_SECONDS=900
MAP_RECONCILIATION_APPLY_STALLED=true
MAP_RECONCILIATION_DELETE_ORPHANS=false
```

Jobs sem atividade são encerrados e têm a reserva devolvida. Órfãos continuam somente reportados;
a exclusão automática deliberadamente permanece desligada. Mantenha exatamente uma instância do
`celery_beat`, embora o advisory lock também proteja contra sobreposição acidental das tasks.

Para disparar uma execução pelo worker e aguardar o resumo:

```bash
docker compose exec backend python manage.py shell -c \
  "from apps.maps.tasks import reconcile_all_tenants; print(reconcile_all_tenants.delay().get(timeout=300))"
```

O resultado contém `status`, totais por categoria e o estado da entrega do alerta.

## Alertas operacionais

Toda execução escreve um resumo estruturado nos logs JSON com quantidade de tenants, jobs
expirados, arquivos ausentes, órfãos e falhas. Quando há anomalias, um webhook HTTPS opcional também
pode receber o evento:

```env
OPERATIONS_ALERT_WEBHOOK_URL=https://alertas.exemplo.com/delta-mapas
OPERATIONS_ALERT_WEBHOOK_SECRET=segredo-independente-para-assinatura
OPERATIONS_ALERT_TIMEOUT_SECONDS=10
OPERATIONS_ALERT_COOLDOWN_SECONDS=21600
```

Sem URL, o modo é `logging_only`. O corpo é JSON e traz `event`, `severity`, `occurred_at`, `summary`,
`incident` e `dedupe_key`. Quando há secret, o header `X-Delta-Mapas-Signature` contém
`sha256=<HMAC-SHA256-do-corpo>`. Eventos idênticos são suprimidos no Redis durante o cooldown; a
chave só é gravada após resposta HTTP bem-sucedida, permitindo nova tentativa no ciclo seguinte em
caso de falha.

Arquivos ausentes ou falhas por tenant geram severidade `critical`. Jobs expirados e órfãos geram
`warning`. Webhooks HTTP são recusados em produção. O destino precisa responder com status 2xx e
deve validar a assinatura antes de processar o evento.
