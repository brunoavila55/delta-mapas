#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
set -a
. ./.env
set +a
task_db="delta_test_$(date +%s)_$$"
docker compose exec -T postgres psql -U delta_owner -d delta_maps -v ON_ERROR_STOP=1 -c "CREATE DATABASE $task_db OWNER delta_app" >/dev/null
cleanup() { docker compose exec -T postgres psql -U delta_owner -d delta_maps -c "DROP DATABASE IF EXISTS $task_db WITH (FORCE)" >/dev/null; }
trap cleanup EXIT INT TERM
docker compose exec -T postgres psql -U delta_owner -d "$task_db" -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION postgis' >/dev/null
TEST_DATABASE_URL="postgres://delta_app:${DELTA_DB_PASSWORD}@127.0.0.1:5439/${task_db}" cargo test --locked --test saas -- --ignored --nocapture
