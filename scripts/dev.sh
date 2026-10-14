#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
set -a
. ./.env
set +a
task_mode="${1:-serve}"
case "$task_mode" in
  serve|worker|migrate) exec cargo run --locked -- "$task_mode" ;;
  *) echo 'Use scripts/dev.sh serve|worker|migrate' >&2; exit 2 ;;
esac
