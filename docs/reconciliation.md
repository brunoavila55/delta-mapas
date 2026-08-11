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

Nesta etapa o comando é manual. Em produção, execute-o periodicamente pelo agendador da plataforma
para cada schema, começando em modo de simulação e enviando a saída aos logs/alertas. O agendamento
automático fica para a configuração de deploy.
