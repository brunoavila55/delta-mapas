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
: "${BACKUP_RETENTION_DAYS:=14}"

case "$BACKUP_RETENTION_DAYS" in
  ''|*[!0-9]*)
    echo "BACKUP_RETENTION_DAYS deve ser um número inteiro não negativo." >&2
    exit 2
    ;;
esac
if ! printf '%s' "$BACKUP_ENVIRONMENT" | grep -Eq '^[A-Za-z0-9._-]{1,64}$'; then
  echo "BACKUP_ENVIRONMENT deve usar somente letras, números, ponto, hífen ou sublinhado." >&2
  exit 2
fi

backup_root=/backups
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
partial="$backup_root/.partial-$timestamp-$$"
snapshot="$backup_root/$timestamp"

mkdir -p "$backup_root" "$partial/minio"
chmod 0700 "$backup_root" "$partial"
cleanup() {
  rm -rf -- "$partial"
}
trap cleanup EXIT HUP INT TERM

echo "Criando dump lógico do PostgreSQL..."
pg_dump \
  --host="$PGHOST" \
  --port="$PGPORT" \
  --username="$POSTGRES_USER" \
  --dbname="$POSTGRES_DB" \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-acl \
  --file="$partial/postgres.dump"
pg_restore --list "$partial/postgres.dump" >/dev/null

echo "Espelhando objetos privados do MinIO..."
export MC_CONFIG_DIR=/tmp/mc
mc alias set local "$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null
mc mirror --overwrite --retry "local/$MINIO_BUCKET" "$partial/minio"

printf '%s\n' \
  "created_at=$timestamp" \
  "postgres_db=$POSTGRES_DB" \
  "minio_bucket=$MINIO_BUCKET" \
  "backup_environment=$BACKUP_ENVIRONMENT" \
  "app_version=${APP_VERSION:-unknown}" \
  >"$partial/manifest.txt"

(
  cd "$partial"
  sha256sum postgres.dump manifest.txt >SHA256SUMS
  find minio -type f -exec sha256sum '{}' ';' >>SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
  openssl dgst -sha256 -hmac "$BACKUP_SIGNING_KEY" -binary SHA256SUMS \
    | base64 >SHA256SUMS.hmac
)

chmod -R go-rwx "$partial"
mv "$partial" "$snapshot"
trap - EXIT HUP INT TERM

find "$backup_root" \
  -mindepth 1 \
  -maxdepth 1 \
  -type d \
  -name '20??????T??????Z' \
  -mtime "+$BACKUP_RETENTION_DAYS" \
  -exec rm -rf -- '{}' ';'

echo "Backup concluído: $timestamp"
