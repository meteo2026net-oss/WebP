#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -z "${CODESPACE_NAME:-}" ]]; then
  echo "This script is intended to run inside GitHub Codespaces." >&2
  echo "Open the repository in Codespaces, then run: bash scripts/start-review-stack.sh" >&2
  exit 2
fi
command -v docker >/dev/null || { echo "Docker CLI is unavailable in this Codespace." >&2; exit 2; }
command -v openssl >/dev/null || { echo "OpenSSL is required." >&2; exit 2; }

CERT_DIR=".devcontainer/certs"
mkdir -p "$CERT_DIR"
if [[ ! -s "$CERT_DIR/ca.crt" || ! -s "$CERT_DIR/server.crt" || ! -s "$CERT_DIR/server.key" ]]; then
  rm -f "$CERT_DIR"/*
  openssl req -x509 -newkey rsa:3072 -nodes -keyout "$CERT_DIR/ca.key" \
    -out "$CERT_DIR/ca.crt" -days 30 -subj "/CN=ECMWF WebP Codespaces Test CA"
  openssl req -newkey rsa:3072 -nodes -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.csr" -subj "/CN=127.0.0.1"
  cat > "$CERT_DIR/server.ext" <<'EOF'
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:db,DNS:localhost,IP:127.0.0.1
EOF
  openssl x509 -req -in "$CERT_DIR/server.csr" -CA "$CERT_DIR/ca.crt" \
    -CAkey "$CERT_DIR/ca.key" -CAcreateserial -out "$CERT_DIR/server.crt" \
    -days 30 -sha256 -extfile "$CERT_DIR/server.ext"
  chmod 600 "$CERT_DIR/ca.key" "$CERT_DIR/server.key"
fi

if [[ ! -s .env ]]; then
  DB_ADMIN_PASSWORD="$(openssl rand -hex 24)"
  KC_ADMIN_PASSWORD="$(openssl rand -hex 24)"
  cat > .env <<EOF
DB_ADMIN_PASSWORD=$DB_ADMIN_PASSWORD
KC_ADMIN_USERNAME=kcadmin
KC_ADMIN_PASSWORD=$KC_ADMIN_PASSWORD
KC_HOSTNAME=https://${CODESPACE_NAME}-8081.app.github.dev
EOF
  chmod 600 .env
fi

docker compose --env-file .env -f .devcontainer/compose.yaml up -d
echo
echo "Services started. Codespaces ports 8081 (Keycloak) and 5432 (PostgreSQL) are private."
echo "Keycloak URL: https://${CODESPACE_NAME}-8081.app.github.dev"
echo "Open the Ports tab and keep Keycloak port 8081 private."
echo "Next: run bash scripts/bootstrap-review-db.sh"
