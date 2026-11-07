# WSGI review REST API

`src/ecmwf_collector/review_api.py` exposes the forecaster review workflow over WSGI.
It is a service component, not a deployed endpoint.

## Trusted identity: OIDC/JWKS

The optional `src/ecmwf_collector/oidc_identity.py` adapter validates bearer access
tokens using the configured OIDC issuer and JWKS endpoint. It accepts RS256 only,
checks issuer, audience, expiry and issued-at claims, requires a subject, and maps
one configured claim through a server-owned allowlist. It does not trust role,
actor, or identity values from request JSON, query parameters, or forwarded headers.
The issuer and JWKS URL must use HTTPS.

Install the server extras with `pip install -e ".[review-server]"`, then configure:

- `ECMWF_OIDC_ISSUER`: exact issuer URL from the identity provider.
- `ECMWF_OIDC_AUDIENCE`: audience registered for this API.
- `ECMWF_OIDC_JWKS_URL`: provider's HTTPS JWKS endpoint.
- `ECMWF_OIDC_ROLE_CLAIM`: one claim containing a single role key (default `review_role`).
- `ECMWF_OIDC_ROLE_MAPPING`: JSON mapping of IdP claim values to `reviewer`,
  `review_lead`, or `admin`. Example:
  `{"wx-forecaster":"reviewer","wx-chief":"review_lead","wx-platform-admin":"admin"}`.

Do not copy the example role names into production unless they match groups
provisioned and governed by the organization. The role mapping is deployment
configuration and must be managed as a secret/configuration asset, not sent by
the client. Tokens are accepted only in `Authorization: Bearer`; cookie-based
sessions and reverse-proxy identity headers are deliberately unsupported.

## PostgreSQL runtime and grants

`src/ecmwf_collector/postgres_review_runtime.py` assembles the WSGI application,
repository, and psycopg connection pool. It rejects database DSNs without
`sslmode=verify-full` or `verify-ca`, requires a database host, and bounds pool
sizes. Supply the DSN through the deployment secret manager; never commit it.

The database administrator must apply `sql/weather_platform_schema.sql` after
installing the required PostGIS extension, then provision a dedicated service
login with only the privileges needed by the review API:
- schema `weather`: USAGE;
- `review_case`: SELECT and UPDATE;
- `review_event`: SELECT and INSERT;
- `field`: SELECT (review queue and approval quality check);
- `publishable_field`: SELECT only.

Do not grant the API login ownership, schema CREATE, superuser, role/database
creation, replication, or bypass-RLS privileges. Keep ingestion and publication
writer credentials separate from the review API login. Validate grants against
the exact PostgreSQL major version and deployment policy before exposing the
service. The API's workflow layer is the authority for transitions; do not expose
the database login to desktop clients.

## Routes and request rules

- `GET /api/v1/reviews`
- `GET /api/v1/reviews/{id}`
- `POST /api/v1/reviews/{id}/assign`
- `POST /api/v1/reviews/{id}/open`
- `POST /api/v1/reviews/{id}/comments`
- `POST /api/v1/reviews/{id}/decision`
- `POST /api/v1/reviews/{id}/reopen`
- `GET /api/v1/publishable/fields`

JSON bodies are limited to 1 MiB. Mutations require a positive
`expected_version`; operation-specific fields are allowlisted. Client-supplied
`actor_id`, `role`, and `quality_status` are rejected. Approval quality is
read from the locked database row. Responses set `Cache-Control: no-store`
and `X-Content-Type-Options: nosniff`.

## Still required before production

Register the actual OIDC application and role/group claims; provision and
migrate a disposable PostgreSQL database; verify grants with positive and
negative tests; place the WSGI app behind a TLS reverse proxy and production
WSGI server; configure rate limits, request IDs, audit-log retention, health
checks, monitoring, backup/restore, and incident response. The desktop review
console and its OIDC sign-in flow are a separate integration step: do not embed
an API client secret or long-lived bearer token in the Windows application.
