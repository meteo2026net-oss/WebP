# WSGI review REST API

`src/ecmwf_collector/review_api.py` is a dependency-free WSGI adapter over
`ReviewApplicationService`. It implements the documented review routes and
JSON request/response boundary without introducing FastAPI or another runtime
dependency into the Windows desktop package.

## Authentication integration is mandatory

Construct `ReviewWsgiApplication(repository, identity_provider_factory)`.
The factory receives the WSGI environment and must validate the deployment's
session/cookie or bearer token cryptographically, then return a request-scoped
`ReviewIdentityProvider`. It must not trust identity or role fields from JSON,
query parameters, or unsigned headers. The API adapter itself deliberately
does not implement an authentication scheme and is not safe to expose publicly
until a real provider is injected.

## Request rules

- JSON bodies are limited to 1 MiB and must be objects.
- Mutations require a positive integer `expected_version`.
- Only operation-specific fields are accepted; `actor_id`, `role`, and
  `quality_status` are rejected as unknown fields.
- Approval quality is read by the repository from the locked database row.
- Responses set `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`.
- Error mapping: 400 malformed request, 401 unauthenticated, 403 forbidden,
  404 missing route/record, 409 stale version, 422 domain validation, 500
  unexpected server error.

## Status

This is an executable WSGI application component, not a deployed service.
A production deployment still needs a verified identity provider, TLS-terminating
server/reverse proxy, connection pool, database grants, secrets management,
request logging/monitoring, and operational deployment configuration.
