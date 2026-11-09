#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f .env ]] || { echo "Run scripts/start-review-stack.sh first." >&2; exit 2; }
set -a
source .env
set +a

for _ in $(seq 1 60); do
  if docker compose --env-file .env -f .devcontainer/compose.yaml exec -T db pg_isready -U review_admin -d weather_review >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
docker compose --env-file .env -f .devcontainer/compose.yaml exec -T db pg_isready -U review_admin -d weather_review

docker compose --env-file .env -f .devcontainer/compose.yaml exec -T db \
  psql -v ON_ERROR_STOP=1 -U review_admin -d weather_review <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;
SQL

docker compose --env-file .env -f .devcontainer/compose.yaml exec -T db \
  psql -v ON_ERROR_STOP=1 -U review_admin -d weather_review < sql/weather_platform_schema.sql

if ! docker compose --env-file .env -f .devcontainer/compose.yaml exec -T db \
  psql -U review_admin -d weather_review -tAc "SELECT 1 FROM pg_roles WHERE rolname='review_api'" | grep -q 1; then
  API_DB_PASSWORD="$(openssl rand -hex 32)"
  docker compose --env-file .env -f .devcontainer/compose.yaml exec -T db \
    psql -v ON_ERROR_STOP=1 -v api_password="$API_DB_PASSWORD" -U review_admin -d weather_review <<'SQL'
CREATE ROLE review_api LOGIN PASSWORD :'api_password';
SQL
  printf '\nAPI_DB_PASSWORD=%s\n' "$API_DB_PASSWORD" >> .env
  chmod 600 .env
fi

docker compose --env-file .env -f .devcontainer/compose.yaml exec -T db \
  psql -v ON_ERROR_STOP=1 -v review_api_role=review_api -U review_admin -d weather_review < sql/review_api_grants.sql

docker compose --env-file .env -f .devcontainer/compose.yaml exec -T db \
  psql -v ON_ERROR_STOP=1 -U review_admin -d weather_review <<'SQL'
INSERT INTO weather.model(code, display_name, provider)
VALUES ('TEST-MODEL', 'Test Forecast Model', 'Codespaces fixture')
ON CONFLICT (code) DO NOTHING;

INSERT INTO weather.variable(code, display_name, canonical_unit)
VALUES ('TEST-T2M', 'Test near-surface temperature', 'K')
ON CONFLICT (code) DO NOTHING;

INSERT INTO weather.level(type_of_level, level_value, level_unit, display_name)
VALUES ('surface', 0, 'surface', 'Surface')
ON CONFLICT (type_of_level, level_value, level_unit) DO NOTHING;

INSERT INTO weather.grid(grid_hash, grid_type, nx, ny, crs)
VALUES (repeat('a',64), 'regular_ll', 1, 1, 'EPSG:4326')
ON CONFLICT (grid_hash) DO NOTHING;

INSERT INTO weather.asset(asset_uri, asset_format, byte_size, sha256, verified)
VALUES ('codespaces://review-fixture/test-field', 'fixture', 0, repeat('b',64), true)
ON CONFLICT (asset_uri) DO NOTHING;

WITH m AS (SELECT model_id FROM weather.model WHERE code='TEST-MODEL'),
r AS (
  INSERT INTO weather.forecast_run(model_id, run_time, source_cycle)
  SELECT model_id, TIMESTAMPTZ '2026-11-08 00:00:00+00', 'codespaces-test'
  FROM m
  ON CONFLICT (model_id, run_time) DO UPDATE SET source_cycle=EXCLUDED.source_cycle
  RETURNING run_id
),
v AS (SELECT variable_id FROM weather.variable WHERE code='TEST-T2M'),
l AS (SELECT level_id FROM weather.level WHERE type_of_level='surface' AND level_value=0 AND level_unit='surface'),
g AS (SELECT grid_id FROM weather.grid WHERE grid_hash=repeat('a',64)),
a AS (SELECT asset_id FROM weather.asset WHERE asset_uri='codespaces://review-fixture/test-field'),
f AS (
  INSERT INTO weather.field(run_id, variable_id, level_id, grid_id, forecast_hour,
    valid_time, source_unit, display_unit, asset_id, value_min, value_max, quality_status)
  SELECT r.run_id, v.variable_id, l.level_id, g.grid_id, 0,
    TIMESTAMPTZ '2026-11-08 00:00:00+00', 'K', 'K', a.asset_id, 280, 281, 'passed'
  FROM r, v, l, g, a
  ON CONFLICT DO NOTHING
  RETURNING field_id
)
INSERT INTO weather.review_case(review_id, field_id)
SELECT 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'::uuid, field_id FROM f
ON CONFLICT (review_id) DO NOTHING;
SQL

echo "Database schema, least-privilege API role, and sample QC-passed field are ready."
echo "Database CA: $ROOT/.devcontainer/certs/ca.crt"
