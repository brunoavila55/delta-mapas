# Deploy de produção na OCI

Este runbook publica o Delta Mapas em uma única VM OCI usando Docker Compose. O Caddy
é a única borda pública; Django, PostgreSQL/PostGIS, Redis e MinIO permanecem acessíveis somente
pela rede interna do Compose.

## Topologia

```text
Internet :80/:443
        │
        ▼
Caddy ── HTTPS automático ──→ Gunicorn/Django + Templates/HTMX
                                      │
                                      ├── PostgreSQL/PostGIS
                                      ├── Redis ← Celery
                                      │             ↑
                                      │        Celery Beat
                                      └── MinIO
```

O Caddy obtém e renova certificados automaticamente. Para isso, o hostname precisa resolver para o
IP público da VM, as portas TCP 80 e 443 devem chegar ao host e o volume `caddy_data` deve ser
preservado.

## 1. Criar a VM e a rede

1. Crie uma VM `VM.Standard.A1.Flex` com Ubuntu 24.04 LTS arm64. Comece com recursos compatíveis com
   o volume esperado; processamento raster, PostGIS e MinIO compartilham a mesma máquina.
2. Reserve um IP público estável e crie o registro DNS `A` do hostname escolhido.
3. Associe um Network Security Group à VNIC e permita entrada stateful somente para:
   - TCP 22 a partir do seu CIDR administrativo;
   - TCP 80 a partir da internet;
   - TCP 443 e UDP 443 a partir da internet.
4. Não abra 5432, 6379, 8000, 9000 ou 9001. O Compose de produção não publica essas portas.

O Docker pode contornar regras do UFW para portas publicadas. Trate o NSG da OCI como a primeira
barreira e, se adicionar regras no host, use a cadeia `DOCKER-USER` conforme a documentação do
Docker.

## 2. Instalar o Docker

Instale Docker Engine, Buildx e o plugin Compose pelo repositório oficial do Docker para Ubuntu. A
instalação suporta `arm64`; confirme o daemon e a arquitetura antes de continuar:

```bash
sudo systemctl status docker
docker version
docker compose version
uname -m
```

O usuário de deploy pode ser adicionado ao grupo `docker`, lembrando que esse grupo equivale a
privilégios administrativos no host.

## 3. Configurar o projeto

Clone uma tag ou commit revisado, copie o modelo de ambiente e proteja o arquivo:

```bash
git clone https://github.com/brunoavila55/delta-mapas.git
cd delta-mapas
cp .env.prod.example .env.prod
chmod 600 .env.prod
```

Preencha todos os valores `replace-with-*`. `APP_DOMAIN` recebe somente o hostname, por exemplo
`mapas.exemplo.com`. Gere valores aleatórios e independentes para Django, PostgreSQL, MinIO e o
proprietário inicial. Defina também uma `BACKUP_SIGNING_KEY` exclusiva e
`BACKUP_ENVIRONMENT=production`. As credenciais `COPERNICUS_CLIENT_ID` e
`COPERNICUS_CLIENT_SECRET` são as do OAuth
client do Sentinel Hub; não use credenciais S3 e não exponha esses valores no navegador.

O serviço `provision` cria de forma idempotente o primeiro tenant, o domínio, o proprietário, o preço
do NDVI e o bônus inicial. A senha em `SUPERUSER_PASSWORD` só é aplicada quando o usuário é criado;
alterações posteriores devem usar `changepassword`.

Apesar dos nomes legados das variáveis, esse usuário não recebe acesso ao Django Admin. Caso seja
necessário operar o admin global, crie uma identidade separada com `python manage.py createsuperuser`
e proteja-a como credencial de plataforma.

Configure `OPERATIONS_ALERT_WEBHOOK_URL` e um secret independente se houver um receptor de alertas.
Sem webhook, os incidentes continuam nos logs estruturados. Não execute mais de uma réplica de
`celery_beat`.

## 4. Validar e iniciar

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml config --quiet
docker compose --env-file .env.prod -f docker-compose.prod.yml build --pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
docker compose --env-file .env.prod -f docker-compose.prod.yml ps -a
```

`migrate`, `provision` e `minio_init` devem terminar com código zero. Os demais serviços devem ficar
ativos e saudáveis. Verifique os logs sem imprimir o arquivo de ambiente:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=200
curl --fail --show-error https://mapas.exemplo.com/health/
```

Antes de liberar usuários, execute a checagem de deploy do Django:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  run --rm backend python manage.py check --deploy
```

Com `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=false` e `DJANGO_SECURE_HSTS_PRELOAD=false`, o Django
reporta `security.W005` e `security.W021`. Esses avisos são deliberados até que todos os subdomínios
estejam definitivamente em HTTPS; revise-os, mas não ative preload sem cumprir esse requisito.

## 5. Atualizar e operar

Faça backup antes de cada atualização. Depois de selecionar uma nova tag ou commit:

```bash
git fetch --tags origin
git checkout <tag-ou-commit-revisado>
docker compose --env-file .env.prod -f docker-compose.prod.yml build --pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --remove-orphans
docker compose --env-file .env.prod -f docker-compose.prod.yml ps -a
```

O `up` executa as migrations e o provisionamento idempotente antes de liberar backend, worker e
proxy. Para trocar a senha do proprietário:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec backend python manage.py changepassword admin
```

Para uma auditoria manual sem alterações:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec backend python manage.py reconcile_maps --schema principal
```

## Backup e recuperação

Mantenha backups criptografados, fora da VM, de três conjuntos inseparáveis:

- dump lógico do PostgreSQL, incluindo todos os schemas;
- dados do volume `minio_data`;
- `.env.prod` ou os segredos equivalentes em um cofre separado.

O serviço operacional `backup` produz um snapshot atômico com dump custom do PostgreSQL, espelho do
bucket MinIO, manifesto, checksums SHA-256 e HMAC dos checksums. Ele valida o arquivo com
`pg_restore --list` antes de publicá-lo e mantém 14 dias por padrão:

```bash
sudo install -d -m 700 /var/backups/delta-mapas
docker compose --env-file .env.prod -f docker-compose.prod.yml --profile ops \
  run --rm backup
```

Configure `BACKUP_DIRECTORY`, `BACKUP_RETENTION_DAYS`, `BACKUP_SIGNING_KEY` e
`BACKUP_ENVIRONMENT` no `.env.prod`. Guarde a chave fora do diretório de snapshots. O diretório local protege
contra falhas lógicas, mas não contra perda da VM: sincronize cada snapshot concluído para OCI Object
Storage ou outro destino externo criptografado. O `.env.prod` deliberadamente não entra no snapshot.

Para automatizar diariamente às 03:15, copie os arquivos de `ops/systemd/` para
`/etc/systemd/system/`, ajuste `WorkingDirectory` caso o repositório não esteja em
`/opt/delta-mapas` e ative o timer:

```bash
sudo cp ops/systemd/delta-mapas-backup.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now delta-mapas-backup.timer
systemctl list-timers delta-mapas-backup.timer
```

Restauração substitui o banco e o bucket atuais. Pare os consumidores, informe somente o nome exato
do snapshot e use a confirmação explícita:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  stop proxy backend celery_worker celery_beat

docker compose --env-file .env.prod -f docker-compose.prod.yml --profile ops \
  run --rm -e RESTORE_CONFIRM=RESTORE backup restore 20260817T030000Z

docker compose --env-file .env.prod -f docker-compose.prod.yml \
  up -d backend celery_worker celery_beat proxy
```

A restauração verifica o HMAC antes dos checksums, recusa snapshots de outro ambiente, usa uma única transação PostgreSQL e aplica
`mc mirror --overwrite --remove` para tornar o bucket idêntico ao snapshot. Ensaie periodicamente em
uma VM ou projeto Compose isolado. Os volumes `postgres_data`, `minio_data` e `caddy_data` não devem
ser removidos em atualizações normais.

## Checklist de liberação

- DNS aponta para a VM e HTTPS está válido;
- somente 22 restrito, 80 e 443 estão publicados no NSG;
- `.env.prod` está com modo 600 e fora do Git;
- os alertas de `check --deploy` foram resolvidos ou têm justificativa documentada;
- serviços permanentes estão saudáveis e serviços one-shot saíram com zero;
- login, criação de job, processamento Copernicus e downloads foram testados;
- `celery_beat` está ativo e uma reconciliação manual retorna `ok` ou um incidente esperado;
- o receptor externo valida `X-Delta-Mapas-Signature` e um alerta de teste foi entregue;
- backup e restauração foram ensaiados;
- métricas, alertas de capacidade e rotação de logs estão habilitados na OCI.

## Referências oficiais

- [OCI Ampere Compute](https://docs.oracle.com/en-us/iaas/Content/Compute/References/arm.htm)
- [OCI Network Security Groups](https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/networksecuritygroups.htm)
- [Docker Engine no Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Docker Compose em produção](https://docs.docker.com/compose/how-tos/production/)
- [Celery — tarefas periódicas](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html)
- [Caddy Automatic HTTPS](https://caddyserver.com/docs/automatic-https)
- [Checklist de deploy do Django](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- [PostgreSQL `pg_dump`](https://www.postgresql.org/docs/17/app-pgdump.html)
- [MinIO `mc mirror`](https://min.io/docs/minio/linux/reference/minio-mc/mc-mirror.html)
