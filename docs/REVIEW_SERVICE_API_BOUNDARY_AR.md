# Review application service and API boundary

## Application service

`src/ecmwf_collector/review_service.py` provides an HTTP-framework-neutral
application service. It injects a `ReviewIdentityProvider`, obtains the
authenticated actor for each operation, and never accepts `actor_id` or
`role` from a request payload.

- Reviewers see only queue items assigned to their authenticated subject.
- Reviewers cannot fetch an unassigned case.
- Review leads and administrators can inspect the complete review queue.
- Mutations delegate to the PostgreSQL repository, which locks the case row,
  validates `expected_version`, reads QC from the database for approvals,
  and commits the state change and audit event together.
- Publishable product reads use only `weather.publishable_field`.

The identity provider must be implemented by the deployment's real session,
OIDC, or JWT-verification layer. `AuthenticatedActor` is an internal trusted
object, not a request schema. Do not deserialize it directly from JSON.

## WSGI REST adapter (implemented; not deployed)

`src/ecmwf_collector/review_api.py` implements the following routes through
`ReviewWsgiApplication`. The component is executable as a WSGI callable, but
there is no production server or verified identity-provider implementation
configured in this repository:

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/v1/reviews` | Auth-scoped review queue |
| GET | `/api/v1/reviews/{review_id}` | Case and audit timeline |
| POST | `/api/v1/reviews/{review_id}/assign` | Lead/admin assignment |
| POST | `/api/v1/reviews/{review_id}/open` | Start review |
| POST | `/api/v1/reviews/{review_id}/comments` | Add review note |
| POST | `/api/v1/reviews/{review_id}/decision` | Approve/reject/request changes |
| POST | `/api/v1/reviews/{review_id}/reopen` | Lead/admin reopen |
| GET | `/api/v1/publishable/fields` | QC-passed and human-approved fields |

Every mutation carries an `expected_version`; the adapter maps stale-version
conflicts to HTTP 409, permission failures to 403, missing records to 404, and
domain validation failures to 422. Authentication failures map to 401. The
adapter rejects client-supplied `actor_id`, `role`, and `quality_status`.
Approval quality is read by the repository from PostgreSQL.

The `identity_provider_factory` must validate a real session or signed token
and return a request-scoped provider. It must not trust unsigned identity
headers, query parameters, or JSON. Cookie-based sessions additionally require
CSRF protection. Do not mount this WSGI callable on a public listener until
these controls, TLS, rate limiting, monitoring, and secret management exist.

## Database privilege outline

Create roles through the deployment's DBA process; do not assume application
startup has permission to create roles. A dedicated review-service role needs
only the schema usage, review-case read/update, review-event insert/read,
forecast-field read, and review-event sequence usage required by the repository.
A separate product-reader role should receive SELECT on
`weather.publishable_field` only, and must not receive SELECT on raw
`weather.field`, `weather.review_case`, or `weather.review_event`.

Example grants (run only after creating the named roles and reviewing the
deployment's broader grants):

```sql
GRANT USAGE ON SCHEMA weather TO weather_review_service;
GRANT SELECT, UPDATE ON weather.review_case TO weather_review_service;
GRANT SELECT, INSERT ON weather.review_event TO weather_review_service;
GRANT USAGE, SELECT ON SEQUENCE weather.review_event_event_id_seq TO weather_review_service;
GRANT SELECT ON weather.field TO weather_review_service;
GRANT SELECT ON weather.publishable_field TO weather_review_service;
GRANT USAGE ON SCHEMA weather TO weather_product_reader;
GRANT SELECT ON weather.publishable_field TO weather_product_reader;
```

These grants are a deployment template, not applied permissions. Check inherited
role memberships and PUBLIC grants; revoke broader privileges where appropriate.

## One-current-review invariant

Each forecast field must have exactly one current review case. The schema adds
a unique index on `review_case(field_id)`; this prevents a previous approved
case from making a later pending/rejected case appear publishable through the
view's EXISTS condition. If a pre-existing database contains duplicate review
cases for one field, the index migration fails intentionally and requires
manual reconciliation rather than silently choosing a record.
