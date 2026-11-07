-- Run as a PostgreSQL administrator after weather schema creation.
-- Supply a pre-created, dedicated LOGIN role via psql -v review_api_role=...
-- This script grants only privileges used by the review API. It does not
-- create credentials, alter ownership, or grant ingestion/publication writes.

GRANT USAGE ON SCHEMA weather TO :"review_api_role";
GRANT SELECT ON TABLE weather.review_case TO :"review_api_role";
GRANT UPDATE (status, assigned_to, review_version, decided_by, decided_at, decision_reason)
    ON TABLE weather.review_case TO :"review_api_role";
GRANT SELECT, INSERT ON TABLE weather.review_event TO :"review_api_role";
GRANT SELECT ON TABLE weather.field TO :"review_api_role";
GRANT SELECT ON TABLE weather.publishable_field TO :"review_api_role";
GRANT USAGE, SELECT ON SEQUENCE weather.review_event_event_id_seq TO :"review_api_role";

-- Deliberately absent: schema CREATE, table ownership, DELETE/TRUNCATE,
-- field INSERT/UPDATE, superuser, BYPASSRLS, role/database creation.
