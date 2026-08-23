#!/bin/sh
set -eu

: "${PGHOST:?PGHOST não definido}"
: "${PGPORT:=5432}"
: "${POSTGRES_DB:?POSTGRES_DB não definido}"
: "${POSTGRES_USER:?POSTGRES_USER não definido}"
: "${PGPASSWORD:?PGPASSWORD não definido}"
: "${MINIO_ENDPOINT:?MINIO_ENDPOINT não definido}"
: "${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY não definido}"
: "${MINIO_SECRET_KEY:?MINIO_SECRET_KEY não definido}"
: "${MINIO_BUCKET:?MINIO_BUCKET não definido}"
: "${BACKUP_SIGNING_KEY:?BACKUP_SIGNING_KEY não definido}"
: "${BACKUP_ENVIRONMENT:?BACKUP_ENVIRONMENT não definido}"

snapshot_name=${1:-}
if [ "${RESTORE_CONFIRM:-}" != "RESTORE" ]; then
  echo "Restauração recusada. Defina RESTORE_CONFIRM=RESTORE explicitamente." >&2
  exit 2
fi
if ! printf '%s' "$snapshot_name" | grep -Eq '^20[0-9]{6}T[0-9]{6}Z$'; then
  echo "Informe somente o nome exato do snapshot, por exemplo 20260817T030000Z." >&2
  exit 2
fi

backup_root=$(realpath /backups)
snapshot=$(realpath "$backup_root/$snapshot_name")
case "$snapshot" in
  "$backup_root"/*) ;;
  *)
    echo "Snapshot fora do diretório permitido." >&2
    exit 2
    ;;
esac

test -f "$snapshot/postgres.dump"
test -f "$snapshot/manifest.txt"
test -f "$snapshot/SHA256SUMS"
test -f "$snapshot/SHA256SUMS.hmac"
test -d "$snapshot/minio"
for required_file in postgres.dump manifest.txt SHA256SUMS SHA256SUMS.hmac; do
  if [ -L "$snapshot/$required_file" ]; then
    echo "Snapshot contém link simbólico não permitido: $required_file" >&2
    exit 2
  fi
done
if find "$snapshot/minio" -type l | grep -q .; then
  echo "Snapshot contém links simbólicos não permitidos no conteúdo do MinIO." >&2
  exit 2
fi

echo "Verificando integridade do snapshot..."
(
  cd "$snapshot"
  signature_file=$(mktemp)
  trap 'rm -f "$signature_file"' EXIT HUP INT TERM
  openssl dgst -sha256 -hmac "$BACKUP_SIGNING_KEY" -binary SHA256SUMS \
    | base64 >"$signature_file"
  if ! cmp -s "$signature_file" SHA256SUMS.hmac; then
    echo "Assinatura do snapshot inválida." >&2
    exit 2
  fi
  if ! grep -Fqx "backup_environment=$BACKUP_ENVIRONMENT" manifest.txt; then
    echo "Snapshot pertence a outro ambiente." >&2
    exit 2
  fi
  sha256sum -c SHA256SUMS
  pg_restore --list postgres.dump >/dev/null
)

echo "Restaurando PostgreSQL em transação única..."
pg_restore \
  --host="$PGHOST" \
  --port="$PGPORT" \
  --username="$POSTGRES_USER" \
  --dbname="$POSTGRES_DB" \
  --clean \
  --if-exists \
  --no-owner \
  --no-acl \
  --single-transaction \
  --exit-on-error \
  "$snapshot/postgres.dump"

echo "Restaurando o bucket privado do MinIO..."
export MC_CONFIG_DIR=/tmp/mc
mc alias set local "$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null
mc mirror --overwrite --remove --retry "$snapshot/minio" "local/$MINIO_BUCKET"

echo "Restauração concluída: $snapshot_name"
