#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=app_password="$APP_DB_PASSWORD" <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE ROLE delta_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'app_password';
GRANT CONNECT ON DATABASE delta_maps TO delta_app;
GRANT USAGE, CREATE ON SCHEMA public TO delta_app;
SQL
