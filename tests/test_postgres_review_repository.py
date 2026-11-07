"""Live PostgreSQL integration tests for transactional review persistence.

These tests are skipped outside CI unless DATABASE_URL points to a disposable
PostgreSQL database with sql/weather_platform_schema.sql already applied.
"""
from __future__ import annotations

import os
import unittest
from uuid import uuid4

import psycopg

from ecmwf_collector.postgres_review_repository import PostgresReviewRepository
from ecmwf_collector.review_workflow import ReviewConflictError, ReviewWorkflowError


DATABASE_URL = os.environ.get("DATABASE_URL")


@unittest.skipUnless(DATABASE_URL, "DATABASE_URL is not configured")
class PostgresReviewRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.token = uuid4().hex
        self.review_id = str(uuid4())
        self.conn = psycopg.connect(DATABASE_URL)
        with self.conn.transaction():
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO weather.model(code, display_name, provider) VALUES (%s, %s, %s) RETURNING model_id",
                (f"test-{self.token}", "Integration test model", "test"),
            )
            model_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO weather.forecast_run(model_id, run_time, source_cycle)
                   VALUES (%s, now(), %s) RETURNING run_id""",
                (model_id, self.token),
            )
            run_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO weather.grid(grid_hash, grid_type, nx, ny)
                   VALUES (%s, 'regular_ll', 2, 2) RETURNING grid_id""",
                (self.token.ljust(64, "0"),),
            )
            grid_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO weather.variable(code, display_name, canonical_unit)
                   VALUES (%s, 'Test temperature', 'K') RETURNING variable_id""",
                (f"t-{self.token}",),
            )
            variable_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO weather.level(type_of_level, level_value, level_unit)
                   VALUES ('surface', 0, 'surface') RETURNING level_id"""
            )
            level_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO weather.asset(asset_uri, asset_format, byte_size, sha256)
                   VALUES (%s, 'GRIB2', 4, %s) RETURNING asset_id""",
                (f"test://{self.token}", "a" * 64),
            )
            asset_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO weather.field(
                       run_id, variable_id, level_id, grid_id, forecast_hour,
                       valid_time, source_unit, display_unit, asset_id, quality_status
                   ) VALUES (%s, %s, %s, %s, 0, now(), 'K', 'K', %s, %s)
                   RETURNING field_id""",
                (run_id, variable_id, level_id, grid_id, asset_id, self.quality_status),
            )
            self.field_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO weather.review_case(review_id, field_id)
                   VALUES (%s, %s)""",
                (self.review_id, self.field_id),
            )
        self.repository = PostgresReviewRepository(lambda: psycopg.connect(DATABASE_URL))

    @property
    def quality_status(self):
        return getattr(self, "_quality_status", "passed")

    @quality_status.setter
    def quality_status(self, value):
        self._quality_status = value

    def tearDown(self):
        with self.conn.transaction():
            self.conn.execute("DELETE FROM weather.review_event WHERE review_id = %s", (self.review_id,))
            self.conn.execute("DELETE FROM weather.review_case WHERE review_id = %s", (self.review_id,))
            self.conn.execute("DELETE FROM weather.field WHERE field_id = %s", (self.field_id,))
            self.conn.execute("DELETE FROM weather.asset WHERE asset_uri = %s", (f"test://{self.token}",))
            self.conn.execute("DELETE FROM weather.level WHERE type_of_level = 'surface' AND level_value = 0 AND level_unit = 'surface'")
            self.conn.execute("DELETE FROM weather.variable WHERE code = %s", (f"t-{self.token}",))
            self.conn.execute("DELETE FROM weather.grid WHERE grid_hash = %s", (self.token.ljust(64, "0"),))
            self.conn.execute("DELETE FROM weather.forecast_run WHERE source_cycle = %s", (self.token,))
            self.conn.execute("DELETE FROM weather.model WHERE code = %s", (f"test-{self.token}",))
        self.conn.close()

    def _transition(self, operation, expected_version, **kwargs):
        return self.repository.transition(
            self.review_id,
            operation=operation,
            actor_id=kwargs.pop("actor_id", "forecaster"),
            role=kwargs.pop("role", "reviewer"),
            expected_version=expected_version,
            **kwargs,
        )

    def test_state_and_audit_event_commit_together(self):
        self._transition("assign", 1, actor_id="lead", role="review_lead", reviewer_id="forecaster")
        self._transition("open", 2)
        approved = self._transition(
            "decide", 3, decision="approved", reason="QC and forecaster checks passed"
        )
        self.assertEqual(approved.status, "approved")
        self.assertEqual(approved.review_version, 4)
        self.assertEqual([event.event_type for event in approved.events],
                         ["assigned", "opened", "approved"])

    def test_approval_reads_quality_status_from_database_and_rolls_back(self):
        self.conn.execute(
            "UPDATE weather.field SET quality_status = 'pending' WHERE field_id = %s",
            (self.field_id,),
        )
        self.conn.commit()
        self._transition("assign", 1, actor_id="lead", role="review_lead", reviewer_id="forecaster")
        self._transition("open", 2)
        with self.assertRaises(ReviewWorkflowError):
            self._transition("decide", 3, decision="approved", reason="Try approval")
        unchanged = self.repository.get_case(self.review_id)
        self.assertEqual(unchanged.status, "in_review")
        self.assertEqual(unchanged.review_version, 3)
        self.assertEqual([event.event_type for event in unchanged.events], ["assigned", "opened"])

    def test_stale_version_is_rejected_without_extra_event(self):
        self._transition("assign", 1, actor_id="lead", role="review_lead", reviewer_id="forecaster")
        with self.assertRaises(ReviewConflictError):
            self._transition("open", 1)
        unchanged = self.repository.get_case(self.review_id)
        self.assertEqual(unchanged.review_version, 2)
        self.assertEqual([event.event_type for event in unchanged.events], ["assigned"])


if __name__ == "__main__":
    unittest.main()
