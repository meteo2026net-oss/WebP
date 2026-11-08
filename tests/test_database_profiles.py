import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ecmwf_collector.database_profiles import (
    DatabaseProfile, DatabaseProfileStore, test_database_connection,
)


class FakeSecrets:
    def __init__(self):
        self.values = {}

    def set_password(self, key, value):
        self.values[key] = value
        return True

    def get_password(self, key):
        return self.values.get(key)

    def delete_password(self, key):
        self.values.pop(key, None)
        return True


class DatabaseProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secrets = FakeSecrets()
        self.store = DatabaseProfileStore(self.root / "connections.json", self.secrets)

    def test_postgres_password_is_not_written_to_profile_file(self):
        profile = self.store.create(
            name="محلي", backend="postgresql", database="weather",
            host="127.0.0.1", port=5432, username="app_user", password="not-in-json",
        )
        raw = (self.root / "connections.json").read_text(encoding="utf-8")
        self.assertNotIn("not-in-json", raw)
        self.assertEqual(self.store.password_for(profile.id), "not-in-json")
        self.assertEqual(DatabaseProfileStore(self.root / "connections.json", self.secrets).get(profile.id), profile)

    def test_sqlite_profile_can_be_tested_without_creating_database(self):
        database = self.root / "existing.db"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE sample (id INTEGER)")
        profile = self.store.create(
            name="SQLite", backend="sqlite", database=str(database),
        )
        result = test_database_connection(profile, self.secrets)
        self.assertTrue(result.ok, result.message)
        self.assertTrue(database.exists())

    def test_missing_sqlite_database_is_not_created(self):
        missing = self.root / "missing.db"
        profile = DatabaseProfile(
            id="missing", name="Missing", backend="sqlite", database=str(missing),
        )
        result = test_database_connection(profile, self.secrets)
        self.assertFalse(result.ok)
        self.assertFalse(missing.exists())

    def test_disable_and_delete_profile(self):
        profile = self.store.create(
            name="PG", backend="postgresql", database="weather",
            host="localhost", port=5432, username="app", password="secret",
        )
        self.store.set_enabled(profile.id, False)
        self.assertFalse(self.store.get(profile.id).enabled)
        self.store.delete(profile.id)
        self.assertEqual(self.store.list_profiles(), [])
        self.assertIsNone(self.secrets.get_password(f"database-profile:{profile.id}"))

    def test_reject_invalid_port(self):
        with self.assertRaises(ValueError):
            DatabaseProfile(
                id="bad", name="Bad", backend="postgresql", database="db",
                host="localhost", port=70000, username="app",
            ).validate()


if __name__ == "__main__":
    unittest.main()
