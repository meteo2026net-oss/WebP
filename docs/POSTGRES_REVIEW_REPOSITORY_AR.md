# PostgreSQL review repository

The in-memory functions in `review_workflow.py` remain the domain policy layer.
`postgres_review_repository.py` adds a psycopg 3 persistence boundary. The
separate `review_api.py` module now provides an executable WSGI REST adapter;
that adapter is not, by itself, a deployed or production-authenticated server.

## Transaction guarantees

- A transition locks its `weather.review_case` row with `FOR UPDATE`.
- The expected `review_version` is checked by the domain layer and again in
  the conditional UPDATE.
- The state update and matching `weather.review_event` insert share one
  database transaction; either both commit or neither does.
- Approval reads `weather.field.quality_status` from the database under
  `FOR SHARE`; request payloads cannot assert that QC passed.
- Event annotations are serialized as JSON and inserted as JSONB.
- Queue reads expose the QC status for review context. Publishable reads use
  only `weather.publishable_field`.

## Identity and database security

The repository does not authenticate users. The caller must obtain `actor_id`
and role from a trusted server-side identity provider; never accept role values
from browser/mobile request bodies. The database role used by public product
readers should receive SELECT only on the publishable view, not on raw
`weather.field` or review tables. The service role needs narrowly scoped
SELECT/UPDATE/INSERT privileges. Configure grants and row-level policies in a
real PostgreSQL deployment before exposing any endpoint.

## Current boundary and deployment status

The repository is called by `ReviewApplicationService`, and the executable
`ReviewWsgiApplication` maps HTTP requests to that service. The WSGI adapter
requires an injected identity-provider factory; no production session, OIDC,
or JWT verifier is implemented here. Do not expose the adapter publicly until
that provider and the deployment controls are in place.

The repository accepts a trusted connection factory, so a future deployment
may pass a psycopg pool connection method. The project does not currently
configure a pool or add `psycopg_pool` as a runtime dependency. A production
setup must size and close the pool deliberately, configure TLS and timeouts,
and keep credentials outside source control.

No live PostgreSQL connection or production schema migration was executed.
The SQL grants are templates only. Review inherited memberships, `PUBLIC`
grants, view ownership/security semantics, and any row-level policies before
exposing product or review data. Cookie-based authentication also requires
CSRF protection; all deployments need rate limiting, request logging, and
secret rotation.
