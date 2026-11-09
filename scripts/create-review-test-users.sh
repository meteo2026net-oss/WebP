#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f .env ]] || { echo "Run scripts/start-review-stack.sh first." >&2; exit 2; }
set -a; source .env; set +a

KC="docker compose --env-file .env -f .devcontainer/compose.yaml exec -T keycloak"
$KC /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master \
  --user "$KC_ADMIN_USERNAME" --password "$KC_ADMIN_PASSWORD" >/dev/null

for role in reviewer review_lead publisher admin; do
  username="test-$role"
  password_var="TEST_${role^^}_PASSWORD"
  if ! grep -q "^$password_var=" .env; then
    password="$(openssl rand -hex 20)"
    printf '%s=%s\n' "$password_var" "$password" >> .env
  else
    password="$(sed -n "s/^$password_var=//p" .env | tail -n 1)"
  fi

  existing="$($KC /opt/keycloak/bin/kcadm.sh get users -r weather-review -q username="$username" --fields id,username)"
  if ! printf '%s' "$existing" | grep -Fq "\"username\" : \"$username\""; then
    $KC /opt/keycloak/bin/kcadm.sh create users -r weather-review \
      -s "username=$username" -s enabled=true \
      -s "attributes.review_role=[\"$role\"]" >/dev/null
  fi
  user_id="$($KC /opt/keycloak/bin/kcadm.sh get users -r weather-review -q username="$username" --fields id | sed -n 's/.*"id" *: *"\([^"]*\)".*/\1/p' | head -n 1)"
  [[ -n "$user_id" ]] || { echo "Could not resolve Keycloak user $username" >&2; exit 1; }
  $KC /opt/keycloak/bin/kcadm.sh set-password -r weather-review --userid "$user_id" --new-password "$password" >/dev/null
done
chmod 600 .env
echo "Created/updated isolated test identities: test-reviewer, test-review_lead, test-publisher, test-admin."
echo "Their generated passwords are stored only in the private Codespace .env file; do not commit or share it."
