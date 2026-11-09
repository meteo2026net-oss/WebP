import json
import tempfile
import unittest
from pathlib import Path

from ecmwf_collector.connection_profiles import (
    DatabaseProfile, DatabaseProfileError, DatabaseProfileStore,
    test_database_connection,
)


class DatabaseProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config" / "database-profiles.json"
        self.store = DatabaseProfileStore(self.path)

    def test_save_and_reload_postgres_metadata(self):
        profile = DatabaseProfile.create(
            "المركز", "postgresql", host="127.0.0.1", port=5432,
            database="weather", username="weather_app", ssl_mode="require",
        )
        self.store.save(profile)
        self.assertEqual(self.store.get(profile.profile_id), profile)

    def test_registry_never_serializes_password_or_dsn(self):
        profile = DatabaseProfile.create(
            "Cloud", "postgresql", host="db.example", port=5432,
            database="weather", username="app",
        )
        self.store.save(profile)
        raw = self.path.read_text(encoding="utf-8")
        self.assertNotIn("password", raw.lower())
        self.assertNotIn("secret-value", raw)
        self.assertNotIn("postgresql://", raw)
        self.assertEqual(json.loads(raw)[0]["credential_key"], profile.credential_key)

    def test_sqlite_profile_requires_path_and_rejects_server_fields(self):
        with self.assertRaises(DatabaseProfileError):
            DatabaseProfile.create("Local", "sqlite").validate()
        with self.assertRaises(DatabaseProfileError):
            DatabaseProfile.create("Local", "sqlite", sqlite_path="state.db",
                                   host="localhost").validate()

    def test_server_profile_validates_port_and_required_fields(self):
        with self.assertRaises(DatabaseProfileError):
            DatabaseProfile.create("Remote", "postgresql", host="db",
                                   database="weather", username="app", port=0).validate()
        with self.assertRaises(DatabaseProfileError):
            DatabaseProfile.create("Remote", "postgresql", host="db", port=5432).validate()

    def test_update_disable_and_delete_profile(self):
        profile = DatabaseProfile.create(
            "Local", "sqlite", sqlite_path="state.db",
        )
        self.store.save(profile)
        disabled = DatabaseProfile(**{**profile.to_metadata(), "enabled": False})
        self.store.save(disabled)
        self.assertFalse(self.store.get(profile.profile_id).enabled)
        self.assertTrue(self.store.delete(profile.profile_id))
        self.assertIsNone(self.store.get(profile.profile_id))
        self.assertFalse(self.store.delete(profile.profile_id))

    def test_duplicate_profile_ids_are_rejected(self):
        profile = DatabaseProfile.create("Local", "sqlite", sqlite_path="state.db")
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps([profile.to_metadata(), profile.to_metadata()]),
                             encoding="utf-8")
        with self.assertRaises(DatabaseProfileError):
            self.store.list_profiles()


    def test_sqlite_connection_test_does_not_create_missing_file(self):
        missing = Path(self.temp.name) / "not-created.db"
        profile = DatabaseProfile.create("Missing", "sqlite", sqlite_path=str(missing))
        ok, message = test_database_connection(profile, secrets=None)
        self.assertFalse(ok)
        self.assertIn("لم يتم إنشاء", message)
        self.assertFalse(missing.exists())

    def test_sqlite_connection_test_runs_read_only_probe(self):
        import sqlite3
        existing = Path(self.temp.name) / "existing.db"
        connection = sqlite3.connect(existing)
        try:
            connection.execute("CREATE TABLE marker (value TEXT)")
            connection.commit()
        finally:
            connection.close()
        profile = DatabaseProfile.create("Existing", "sqlite", sqlite_path=str(existing))
        ok, message = test_database_connection(profile, secrets=None)
        self.assertTrue(ok, message)

    def test_mysql_connection_fails_closed_without_vault_password(self):
        profile = DatabaseProfile.create(
            "MySQL", "mysql", host="localhost", port=3306,
            database="weather", username="app", ssl_mode="prefer",
        )
        ok, message = test_database_connection(profile, secrets=None)
        self.assertFalse(ok)
        self.assertIn("DatabaseDriverError", message)

    def test_mysql_connection_probe_uses_vault_and_disables_ssl_only_when_requested(self):
        import sys
        from types import ModuleType
        from unittest.mock import patch

        class FakeCursor:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql):
                self.sql = sql
            def fetchone(self):
                return (1,)
            def fetchall(self):
                return [("GRANT SELECT, INSERT, UPDATE, DELETE ON weather.* TO 'app'@'%'",)]

        class FakeConnection:
            def __init__(self):
                self.closed = False
            def cursor(self):
                return FakeCursor()
            def close(self):
                self.closed = True

        class FakeSecrets:
            def get_password(self, key):
                return "vault-secret"

        connection = FakeConnection()
        driver = ModuleType("pymysql")
        captured = {}
        def connect(**kwargs):
            captured.update(kwargs)
            return connection
        driver.connect = connect
        profile = DatabaseProfile.create(
            "MySQL", "mysql", host="localhost", port=3306,
            database="weather", username="app", ssl_mode="disable",
        )
        with patch.dict(sys.modules, {"pymysql": driver}):
            ok, message = test_database_connection(profile, FakeSecrets())
        self.assertTrue(ok, message)
        self.assertTrue(connection.closed)
        self.assertEqual(captured["password"], "vault-secret")
        self.assertTrue(captured["ssl_disabled"])
        self.assertEqual(captured["database"], "weather")

    def test_mysql_verify_full_passes_ca_and_hostname_verification(self):
        import ssl
        import sys
        from types import ModuleType
        from unittest.mock import patch

        class FakeCursor:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql):
                pass
            def fetchone(self):
                return (1,)
            def fetchall(self):
                return [("GRANT SELECT, INSERT, UPDATE, DELETE ON weather.* TO 'app'@'%'",)]

        class FakeConnection:
            def cursor(self):
                return FakeCursor()
            def close(self):
                pass

        class FakeSecrets:
            def get_password(self, key):
                return "vault-secret"

        ca_path = Path(self.temp.name) / "root-ca.pem"
        ca_path.write_text("test certificate placeholder", encoding="utf-8")
        captured = {}
        driver = ModuleType("pymysql")
        driver.connect = lambda **kwargs: (captured.update(kwargs) or FakeConnection())
        profile = DatabaseProfile.create(
            "MySQL TLS", "mysql", host="db.example", port=3306,
            database="weather", username="app", ssl_mode="verify-full",
            ssl_ca=str(ca_path),
        )
        with patch.dict(sys.modules, {"pymysql": driver}):
            ok, message = test_database_connection(profile, FakeSecrets())
        self.assertTrue(ok, message)
        self.assertEqual(captured["ssl"]["ca"], str(ca_path))
        self.assertEqual(captured["ssl"]["verify_mode"], ssl.CERT_REQUIRED)
        self.assertTrue(captured["ssl"]["check_hostname"])

    def test_mysql_global_admin_grant_is_rejected(self):
        from ecmwf_collector.database_drivers import DatabaseDriverError, assert_mysql_application_role

        class Cursor:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql):
                self.sql = sql
            def fetchall(self):
                return [("GRANT ALL PRIVILEGES ON *.* TO 'app'@'%'",)]

        class Connection:
            def cursor(self):
                return Cursor()

        with self.assertRaises(DatabaseDriverError):
            assert_mysql_application_role(Connection())

    def test_mysql_global_read_grant_is_rejected(self):
        from ecmwf_collector.database_drivers import DatabaseDriverError, assert_mysql_application_role

        class Cursor:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql):
                pass
            def fetchall(self):
                return [("GRANT SELECT ON *.* TO 'app'@'%'",)]

        class Connection:
            def cursor(self):
                return Cursor()

        with self.assertRaises(DatabaseDriverError):
            assert_mysql_application_role(Connection(), "weather")

    def test_mysql_grant_outside_selected_database_is_rejected(self):
        from ecmwf_collector.database_drivers import DatabaseDriverError, assert_mysql_application_role

        class Cursor:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql):
                pass
            def fetchall(self):
                return [("GRANT SELECT ON otherdb.* TO 'app'@'%'",)]

        class Connection:
            def cursor(self):
                return Cursor()

        with self.assertRaises(DatabaseDriverError):
            assert_mysql_application_role(Connection(), "weather")

    def test_mysql_schema_ddl_grant_is_rejected(self):
        from ecmwf_collector.database_drivers import DatabaseDriverError, assert_mysql_application_role

        class Cursor:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql):
                pass
            def fetchall(self):
                return [("GRANT SELECT, CREATE ON weather.* TO 'app'@'%'",)]

        class Connection:
            def cursor(self):
                return Cursor()

        with self.assertRaises(DatabaseDriverError):
            assert_mysql_application_role(Connection(), "weather")

    def test_mysql_schema_scoped_crud_grants_are_accepted(self):
        from ecmwf_collector.database_drivers import assert_mysql_application_role

        class Cursor:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql):
                self.sql = sql
            def fetchall(self):
                return [("GRANT SELECT, INSERT, UPDATE, DELETE ON weather.* TO 'app'@'%'",)]

        class Connection:
            def cursor(self):
                return Cursor()

        assert_mysql_application_role(Connection())

    def test_mysql_certificate_verification_requires_ca_file(self):
        with self.assertRaises(DatabaseProfileError):
            DatabaseProfile.create(
                "MySQL TLS", "mysql", host="localhost", port=3306,
                database="weather", username="app", ssl_mode="verify-full",
            ).validate()

    def test_secret_and_profile_are_removed_together(self):
        class FakeSecrets:
            def __init__(self):
                self.deleted = []
                self.values = {}
            def get_password(self, key):
                return self.values.get(key)
            def set_password(self, key, value):
                self.values[key] = value
                return True
            def delete_password(self, key):
                self.deleted.append(key)
                self.values.pop(key, None)
                return True
        profile = DatabaseProfile.create(
            "Remote", "postgresql", host="db", port=5432,
            database="weather", username="app",
        )
        self.store.save(profile)
        secrets = FakeSecrets()
        secrets.values[profile.credential_key] = "vault-secret"
        self.assertTrue(self.store.delete_with_secret(profile.profile_id, secrets))
        self.assertIsNone(self.store.get(profile.profile_id))
        self.assertEqual(secrets.deleted, [profile.credential_key])


    def test_failed_profile_delete_restores_vault_secret(self):
        class FailingStore(DatabaseProfileStore):
            def delete(self, profile_id):
                raise OSError("simulated metadata write failure")

        class FakeSecrets:
            def __init__(self):
                self.value = "vault-secret"
            def get_password(self, key):
                return self.value
            def delete_password(self, key):
                self.value = None
                return True
            def set_password(self, key, value):
                self.value = value
                return True

        store = FailingStore(self.path)
        profile = DatabaseProfile.create(
            "Remote", "postgresql", host="db", port=5432,
            database="weather", username="app",
        )
        store.save(profile)
        secrets = FakeSecrets()
        with self.assertRaises(OSError):
            store.delete_with_secret(profile.profile_id, secrets)
        self.assertEqual(secrets.value, "vault-secret")
        self.assertEqual(store.get(profile.profile_id), profile)

    def test_failed_secret_deletion_preserves_profile_metadata(self):
        class FailingSecrets:
            def get_password(self, key):
                return "vault-secret"
            def delete_password(self, key):
                return False
        profile = DatabaseProfile.create(
            "Remote", "postgresql", host="db", port=5432,
            database="weather", username="app",
        )
        self.store.save(profile)
        self.assertFalse(self.store.delete_with_secret(profile.profile_id, FailingSecrets()))
        self.assertEqual(self.store.get(profile.profile_id), profile)

    def test_profile_password_uses_os_secret_store_adapter(self):
        class FakeSecrets:
            def __init__(self):
                self.values = {}
            def set_password(self, key, password):
                self.values[key] = password
                return True
            def get_password(self, key):
                return self.values.get(key)
        profile = DatabaseProfile.create(
            "Remote", "postgresql", host="db.example", port=5432,
            database="weather", username="app",
        )
        secrets = FakeSecrets()
        self.assertTrue(self.store.set_password(profile, secrets, "vault-only-value"))
        self.assertEqual(self.store.get_password(profile, secrets), "vault-only-value")
        self.assertNotIn("vault-only-value", self.path.read_text(encoding="utf-8") if self.path.exists() else "")


if __name__ == "__main__":
    unittest.main()
