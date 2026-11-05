import sys
import types
import unittest
from unittest.mock import patch


class PostgresUpsertTests(unittest.TestCase):
    def setUp(self):
        self.statements = []
        self.params = []

        class FakeConnection:
            def __enter__(inner):
                return inner
            def __exit__(inner, *_args):
                return False
            def execute(inner, statement, params=None):
                self.statements.append(str(statement))
                self.params.append(params)
                if "FROM pg_roles WHERE rolname = current_user" in str(statement):
                    return types.SimpleNamespace(fetchone=lambda: (False, False, False, False, False))
                if "pg_has_role(current_user" in str(statement):
                    return types.SimpleNamespace(fetchone=lambda: None)
                if "has_database_privilege" in str(statement):
                    return types.SimpleNamespace(fetchone=lambda: (True, True, True, True, True, True, True))
                return types.SimpleNamespace(fetchone=lambda: None)

        self.fake_psycopg = types.SimpleNamespace(connect=lambda *_a, **_k: FakeConnection())
        self.patch = patch.dict(sys.modules, {"psycopg": self.fake_psycopg})
        self.patch.start()
        from ecmwf_collector.postgres_state import PostgresStateStore
        self.store = PostgresStateStore("host=127.0.0.1 dbname=weatherdb")
        self.statements.clear()
        self.params.clear()

    def tearDown(self):
        self.patch.stop()

    def test_upsert_uses_one_atomic_insert_on_conflict_statement(self):
        self.store.upsert("/archive/a.grib", status="downloaded", sha256="abc")
        self.assertEqual(len(self.statements), 1)
        statement = self.statements[0]
        self.assertIn("INSERT INTO public.files", statement)
        self.assertIn("ON CONFLICT (remote_path) DO UPDATE SET", statement)
        self.assertIn("status=EXCLUDED.status", statement)
        self.assertIn("sha256=EXCLUDED.sha256", statement)
        self.assertEqual(self.params[0][0], "/archive/a.grib")
        self.assertEqual(self.params[0][1:3], ("downloaded", "abc"))

    def test_empty_upsert_does_not_reset_existing_status(self):
        self.store.upsert("/archive/a.grib")
        statement = self.statements[0]
        self.assertIn("status", statement.split("VALUES", 1)[0])
        self.assertIn("DO UPDATE SET updated_at=EXCLUDED.updated_at", statement)
        self.assertNotIn("status=EXCLUDED.status", statement)

    def test_unknown_fields_are_rejected_before_database_write(self):
        with self.assertRaises(ValueError):
            self.store.upsert("/archive/a.grib", unknown_field="x")
        self.assertEqual(self.statements, [])


if __name__ == "__main__":
    unittest.main()
