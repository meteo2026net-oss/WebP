#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f .env ]] || { echo "Run scripts/start-review-stack.sh first." >&2; exit 2; }
[[ -n "${CODESPACE_NAME:-}" ]] || { echo "Run this inside GitHub Codespaces." >&2; exit 2; }
set -a; source .env; set +a
: "${API_DB_PASSWORD:?Run scripts/bootstrap-review-db.sh first}"
export ECMWF_REVIEW_DATABASE_DSN="host=127.0.0.1 port=5432 dbname=weather_review user=review_api password=$API_DB_PASSWORD sslmode=verify-full sslrootcert=$PWD/.devcontainer/certs/ca.crt"
export ECMWF_OIDC_ISSUER="https://$CODESPACE_NAME-8081.app.github.dev/realms/weather-review"
export ECMWF_OIDC_AUDIENCE="review-api"
export ECMWF_OIDC_JWKS_URL="http://127.0.0.1:8081/realms/weather-review/protocol/openid-connect/certs"
export ECMWF_OIDC_ROLE_CLAIM="review_role"
export ECMWF_OIDC_ROLE_MAPPING='{"reviewer":"reviewer","review_lead":"review_lead","publisher":"publisher","admin":"admin"}'
echo "Starting private Review API at https://$CODESPACE_NAME-8000.app.github.dev"
exec gunicorn --bind 0.0.0.0:8000 --workers 2 --access-logfile - scripts.review_api_dev:application
