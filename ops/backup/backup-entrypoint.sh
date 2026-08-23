#!/bin/sh
set -eu

case "${1:-backup}" in
  backup)
    shift || true
    exec /usr/local/bin/backup.sh "$@"
    ;;
  restore)
    shift
    exec /usr/local/bin/restore.sh "$@"
    ;;
  *)
    echo "Uso: backup-entrypoint.sh [backup|restore <snapshot>]" >&2
    exit 2
    ;;
esac
