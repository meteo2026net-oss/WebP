"""Live PostgreSQL integration for the least-privilege state backend.

Runs only when POSTGRES_STATE_ADMIN_DSN points at a disposable test database.
"""
from __future__ import annotations

import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

try:
    import psycopg
    from psycopg import sql
except ImportError:  # pragma: no cover - CI installs psycopg
    psycopg = None
    sql = None


ADMIN_DSN = os.environ.get("POSTGRES_STATE_ADMIN_DSN", "").strip()


@unittest.skipUnless(ADMIN_DSN and psycopg is not None, "live PostgreSQL test is not configured")
class PostgresStateLiveIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ecmwf_collector.postgres_state import CREATE_TABLE
        cls.admin_dsn = ADMIN_DSN
        cls.role = "webp_state_it_" + uuid.uuid4().hex[:12]
        cls.password = uuid.uuid4().hex + uuid.uuid4().hex
        with psycopg.connect(cls.admin_dsn, autocommit=True) as conn:
            conn.execute(CREATE_TABLE)
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(cls.role), sql.Literal(cls.password))
            )
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(conn.info.dbname), sql.Identifier(cls.role)
                )
            )
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(cls.role)))
            conn.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.files TO {}").format(
                    sql.Identifier(cls.role)
                )
            )
        cls.app_dsn = psycopg.conninfo.make_conninfo(
            cls.admin_dsn, user=cls.role, password=cls.password
        )

    @classmethod
    def tearDownClass(cls):
        if not ADMIN_DSN or psycopg is None or not hasattr(cls, "role"):
            return
        with psycopg.connect(cls.admin_dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("REVOKE ALL PRIVILEGES ON TABLE public.files FROM {}").format(
                    sql.Identifier(cls.role)
                )
            )
            conn.execute(sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(sql.Identifier(cls.role)))
            conn.execute(
                sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
                    sql.Identifier(conn.info.dbname), sql.Identifier(cls.role)
                )
            )
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(cls.role)))

    def setUp(self):
        with psycopg.connect(self.admin_dsn) as conn:
            conn.execute("DELETE FROM public.files WHERE remote_path LIKE %s", ("/it/%",))

    def test_restricted_role_real_connection_crud_and_atomic_conflict(self):
        from ecmwf_collector.postgres_state import PostgresStateStore

        store = PostgresStateStore(self.app_dsn)
        try:
            path = "/it/live-record.grib2"
            store.upsert(path, status="pending", remote_size=123)
            first = store.get(path)
            self.assertIsNotNone(first)
            self.assertEqual(first.status, "pending")
            self.assertEqual(first.remote_size, 123)

            store.upsert(path, status="downloaded", local_size=123, sha256="a" * 64)
            updated = store.get(path)
            self.assertEqual(updated.status, "downloaded")
            self.assertEqual(updated.sha256, "a" * 64)

            store.bump_attempts(path)
            self.assertEqual(store.get(path).attempts, 1)
            self.assertGreaterEqual(store.count(), 1)
            self.assertTrue(any(row.remote_path == path for row in store.all_records()))

            # Two independent store objects/connections race on one primary key.
            barrier = threading.Barrier(2)
            def write(value):
                worker = PostgresStateStore(self.app_dsn)
                try:
                    barrier.wait(timeout=10)
                    worker.upsert(path, status="downloaded", last_error=value)
                finally:
                    worker.close()
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(write, ("worker-a", "worker-b")))
            final = store.get(path)
            self.assertIn(final.last_error, ("worker-a", "worker-b"))
        finally:
            store.close()

    def test_real_server_rejects_app_role_without_table_read_permission(self):
        from ecmwf_collector.postgres_state import PostgresStateStore

        with psycopg.connect(self.admin_dsn, autocommit=True) as conn:
            conn.execute(
                sql.SQL("REVOKE SELECT ON TABLE public.files FROM {}").format(sql.Identifier(self.role))
            )
        try:
            with self.assertRaisesRegex(RuntimeError, "صلاحيات القراءة والكتابة"):
                PostgresStateStore(self.app_dsn)
        finally:
            with psycopg.connect(self.admin_dsn, autocommit=True) as conn:
                conn.execute(
                    sql.SQL("GRANT SELECT ON TABLE public.files TO {}").format(sql.Identifier(self.role))
                )


if __name__ == "__main__":
    unittest.main()
