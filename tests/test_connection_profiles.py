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

    def test_mysql_connection_is_not_falsely_reported_as_supported(self):
        profile = DatabaseProfile.create(
            "MySQL", "mysql", host="localhost", port=3306,
            database="weather", username="app",
        )
        ok, message = test_database_connection(profile, secrets=None)
        self.assertFalse(ok)
        self.assertIn("غير متاح بعد", message)

    def test_secret_is_deleted_only_after_profile_metadata(self):
        class FakeSecrets:
            def __init__(self):
                self.deleted = []
            def delete_password(self, key):
                self.deleted.append(key)
                return True
        profile = DatabaseProfile.create(
            "Remote", "postgresql", host="db", port=5432,
            database="weather", username="app",
        )
        self.store.save(profile)
        secrets = FakeSecrets()
        self.assertTrue(self.store.delete_with_secret(profile.profile_id, secrets))
        self.assertIsNone(self.store.get(profile.profile_id))
        self.assertEqual(secrets.deleted, [profile.credential_key])


    def test_failed_secret_deletion_preserves_profile_metadata(self):
        class FailingSecrets:
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
