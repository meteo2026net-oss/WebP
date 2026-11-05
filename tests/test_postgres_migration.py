import tempfile
import unittest
from pathlib import Path

from ecmwf_collector.state import StateStore
from ecmwf_collector.tools.migrate_sqlite_to_postgres import create_sqlite_backup


class SQLiteBackupTests(unittest.TestCase):
    def test_online_backup_preserves_all_state_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_path = root / "source.db"
            backup_path = root / "backup.db"
            source = StateStore(source_path)
            try:
                source.upsert(
                    "/archive/sample.grib",
                    status="downloaded",
                    remote_size=1234,
                    local_size=1234,
                    sha256="a" * 64,
                    attempts=2,
                    validation="valid",
                )
                expected = source.all_records()
                create_sqlite_backup(source_path, backup_path)
            finally:
                source.close()

            backup = StateStore(backup_path)
            try:
                self.assertEqual(backup.all_records(), expected)
            finally:
                backup.close()


class PostgresProvisionTests(unittest.TestCase):
    def test_provision_quotes_generated_secret_and_saves_app_login_only(self):
        import contextlib
        import sys
        import types
        from unittest.mock import patch

        from ecmwf_collector.postgres_provision import provision_application_login

        calls = []

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def transaction(self):
                return contextlib.nullcontext()

            def execute(self, statement, params=None):
                calls.append((str(statement), params))
                if "current_database" in str(statement):
                    return types.SimpleNamespace(fetchone=lambda: ("weatherdb",))
                if "FROM pg_roles" in str(statement):
                    return types.SimpleNamespace(fetchone=lambda: None)
                return types.SimpleNamespace(fetchone=lambda: None)

        class FakeSQL(str):
            def format(self, *values):
                result = self
                for value in values:
                    result = result.replace("{}", str(value), 1)
                return result

        literal_values = []
        fake_sql = types.SimpleNamespace(
            SQL=lambda value: FakeSQL(value),
            Identifier=lambda value: '"' + value.replace('"', '""') + '"',
            Literal=lambda value: literal_values.append(value) or "'" + value.replace("'", "''") + "'",
        )
        fake_psycopg = types.SimpleNamespace(
            sql=fake_sql,
            conninfo=types.SimpleNamespace(
                make_conninfo=lambda dsn, **kwargs: " ".join(
                    [part for part in dsn.split() if part.split("=", 1)[0] not in kwargs]
                    + [f"{key}={value}" for key, value in kwargs.items()]
                )
            ),
            connect=lambda *_args, **_kwargs: FakeConnection(),
        )
        fake_store = types.SimpleNamespace(close=lambda: None)
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}), patch(
            "ecmwf_collector.postgres_state.PostgresStateStore", return_value=fake_store
        ) as store:
            app_dsn = provision_application_login("host=127.0.0.1 dbname=weatherdb user=admin password=admin-secret")

        self.assertIn("ecmwf_webp_app", app_dsn)
        self.assertNotIn("admin-secret", app_dsn)
        create_role = next(item for item in calls if item[0].startswith("CREATE ROLE"))
        self.assertEqual(len(literal_values), 1)
        self.assertIn(literal_values[0], create_role[0])
        for restricted_flag in (
            "NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE", "NOREPLICATION", "NOBYPASSRLS"
        ):
            self.assertIn(restricted_flag, create_role[0])
        self.assertTrue(any("GRANT CONNECT ON DATABASE" in item[0] for item in calls))
        self.assertTrue(any("GRANT USAGE ON SCHEMA public" in item[0] for item in calls))
        self.assertTrue(any("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.files" in item[0] for item in calls))
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS public.files" in item[0] for item in calls))
        self.assertFalse(any("GRANT USAGE, CREATE ON SCHEMA public" in item[0] for item in calls))
        store.assert_called_once()

    def test_existing_app_role_is_not_overwritten(self):
        import contextlib
        import sys
        import types
        from unittest.mock import patch

        from ecmwf_collector.postgres_provision import provision_application_login

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, statement, params=None):
                if "current_database" in str(statement):
                    return types.SimpleNamespace(fetchone=lambda: ("weatherdb",))
                if "FROM pg_roles" in str(statement):
                    return types.SimpleNamespace(fetchone=lambda: (1,))
                raise AssertionError("No provisioning SQL should run for an existing role.")

            def transaction(self):
                return contextlib.nullcontext()

        fake_sql = types.SimpleNamespace(
            SQL=lambda value: value,
            Identifier=lambda value: '"' + value.replace('"', '""') + '"',
            Literal=lambda value: "'" + value.replace("'", "''") + "'",
        )
        fake_psycopg = types.SimpleNamespace(
            sql=fake_sql, connect=lambda *_a, **_k: FakeConnection()
        )
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            with self.assertRaisesRegex(RuntimeError, "موجود مسبقاً"):
                provision_application_login("host=127.0.0.1 dbname=weatherdb")


    def test_failed_app_login_removes_new_role_grants(self):
        import contextlib
        import sys
        import types
        from unittest.mock import patch

        from ecmwf_collector.postgres_provision import provision_application_login

        statements = []

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def transaction(self):
                return contextlib.nullcontext()

            def execute(self, statement, params=None):
                statement = str(statement)
                statements.append(statement)
                if "current_database" in statement:
                    return types.SimpleNamespace(fetchone=lambda: ("weatherdb",))
                if "FROM pg_roles" in statement:
                    return types.SimpleNamespace(fetchone=lambda: None)
                return types.SimpleNamespace(fetchone=lambda: None)

        class FakeSQL(str):
            def format(self, *values):
                result = self
                for value in values:
                    result = result.replace("{}", str(value), 1)
                return result

        fake_sql = types.SimpleNamespace(
            SQL=lambda value: FakeSQL(value),
            Identifier=lambda value: '"' + value.replace('"', '""') + '"',
            Literal=lambda value: "'" + value.replace("'", "''") + "'",
        )
        fake_psycopg = types.SimpleNamespace(
            sql=fake_sql,
            conninfo=types.SimpleNamespace(make_conninfo=lambda dsn, **kwargs: dsn),
            connect=lambda *_a, **_k: FakeConnection(),
        )
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}), patch(
            "ecmwf_collector.postgres_state.PostgresStateStore",
            side_effect=RuntimeError("connection failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "تعذّر تهيئة حساب PostgreSQL"):
                provision_application_login("host=127.0.0.1 dbname=weatherdb")

        self.assertTrue(any("REVOKE CONNECT ON DATABASE" in item for item in statements))
        self.assertTrue(any("REVOKE ALL PRIVILEGES ON SCHEMA public" in item for item in statements))
        self.assertTrue(any("DROP ROLE IF EXISTS ecmwf_webp_app" in item for item in statements))


class ConfigurePostgresCliTests(unittest.TestCase):
    def test_cli_saves_only_the_restricted_application_dsn(self):
        import contextlib
        import io
        import sys
        from unittest.mock import patch

        from ecmwf_collector.tools import configure_postgres

        admin_dsn = "host=127.0.0.1 dbname=weatherdb user=postgres password=admin-secret"
        app_dsn = "host=127.0.0.1 dbname=weatherdb user=ecmwf_webp_app password=app-secret"

        class FakeSecrets:
            available = True

            def __init__(self):
                self.saved = None

            def set_postgres_dsn(self, value):
                self.saved = value
                return True

        secrets_store = FakeSecrets()
        output = io.StringIO()
        with (
            patch.object(configure_postgres, "SecretStore", return_value=secrets_store),
            patch.object(configure_postgres.getpass, "getpass", return_value=admin_dsn),
            patch.object(configure_postgres, "provision_application_login", return_value=app_dsn),
            patch.object(sys, "argv", ["configure_postgres"]),
            contextlib.redirect_stdout(output),
        ):
            result = configure_postgres.main()

        self.assertEqual(result, 0)
        self.assertEqual(secrets_store.saved, app_dsn)
        self.assertNotEqual(secrets_store.saved, admin_dsn)
        self.assertNotIn("admin-secret", output.getvalue())
        self.assertNotIn("app-secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
