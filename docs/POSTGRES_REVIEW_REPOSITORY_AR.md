# PostgreSQL review repository

The in-memory functions in `review_workflow.py` remain the domain policy layer.
`postgres_review_repository.py` adds a psycopg 3 persistence boundary without
introducing an HTTP framework or pretending that an API server is deployed.

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

## Current boundary

This is a repository/service layer, not a deployed REST API. FastAPI was not
added because no HTTP framework or server/authentication configuration exists
in the project yet. A later API adapter must derive identity server-side,
validate request schemas, apply rate limits, and call this repository.
No live PostgreSQL connection or schema migration was executed by this change.
