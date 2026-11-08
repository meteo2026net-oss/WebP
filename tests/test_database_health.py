import sqlite3
import tempfile
import unittest
from pathlib import Path

from ecmwf_collector.connection_profiles import DatabaseProfile
from ecmwf_collector.database_health import inspect_database


class DatabaseHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.db"

    def _profile(self, enabled=True):
        return DatabaseProfile.create(
            "Local tracking", "sqlite", sqlite_path=str(self.path), enabled=enabled
        )

    def test_reads_tracking_counts_and_sizes_without_writing(self):
        db = sqlite3.connect(self.path)
        try:
            db.execute("""CREATE TABLE files (
                remote_path TEXT PRIMARY KEY, status TEXT NOT NULL,
                remote_size INTEGER, local_size INTEGER, updated_at TEXT
            )""")
            db.executemany(
                "INSERT INTO files VALUES (?, ?, ?, ?, ?)",
                [
                    ("/a.csv", "complete", 100, 100, "2026-11-01T00:00:00+00:00"),
                    ("/b.csv", "failed", 200, 20, "2026-11-02T00:00:00+00:00"),
                    ("/c.csv", "pending", 300, 0, "2026-11-03T00:00:00+00:00"),
                ],
            )
            db.commit()
        finally:
            db.close()
        before = self.path.read_bytes()
        result = inspect_database(self._profile(), secrets=None)
        self.assertTrue(result.connected)
        self.assertTrue(result.tracking_table_available)
        self.assertEqual(result.tracked_files, 3)
        self.assertEqual(result.completed_files, 1)
        self.assertEqual(result.failed_files, 1)
        self.assertEqual(result.remote_bytes, 600)
        self.assertEqual(result.local_bytes, 120)
        self.assertEqual(result.database_bytes, self.path.stat().st_size)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_sqlite_file_is_not_created(self):
        result = inspect_database(self._profile(), secrets=None)
        self.assertFalse(result.connected)
        self.assertFalse(self.path.exists())

    def test_database_without_tracking_table_is_reported_clearly(self):
        connection = sqlite3.connect(self.path)
        connection.close()
        result = inspect_database(self._profile(), secrets=None)
        self.assertTrue(result.connected)
        self.assertFalse(result.tracking_table_available)
        self.assertIsNone(result.tracked_files)

    def test_disabled_profile_is_not_opened(self):
        result = inspect_database(self._profile(enabled=False), secrets=None)
        self.assertFalse(result.connected)
        self.assertIn("معطّل", result.message)
        self.assertFalse(self.path.exists())

    def test_mysql_health_reads_tracking_metrics_and_closes_connection(self):
        import sys
        from types import ModuleType
        from unittest.mock import patch

        class FakeCursor:
            def __init__(self):
                self.rows = [(2048,), (1,), (3, 1, 1, 600, 120, "2026-11-03 00:00:00")]
                self.statements = []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql, params=None):
                self.statements.append(sql.strip().upper())
            def fetchone(self):
                return self.rows.pop(0)

        class FakeConnection:
            def __init__(self):
                self.fake_cursor = FakeCursor()
                self.closed = False
            def cursor(self):
                return self.fake_cursor
            def close(self):
                self.closed = True

        class FakeSecrets:
            def get_password(self, key):
                return "vault-secret"

        connection = FakeConnection()
        driver = ModuleType("pymysql")
        driver.connect = lambda **kwargs: connection
        profile = DatabaseProfile.create(
            "MariaDB", "mariadb", host="localhost", port=3306,
            database="weather", username="app", ssl_mode="disable",
        )
        with patch.dict(sys.modules, {"pymysql": driver}):
            result = inspect_database(profile, FakeSecrets())
        self.assertTrue(result.connected)
        self.assertTrue(result.tracking_table_available)
        self.assertEqual(result.tracked_files, 3)
        self.assertEqual(result.completed_files, 1)
        self.assertEqual(result.failed_files, 1)
        self.assertEqual(result.remote_bytes, 600)
        self.assertEqual(result.local_bytes, 120)
        self.assertEqual(result.database_bytes, 2048)
        self.assertTrue(connection.closed)
        self.assertTrue(all(sql.startswith("SELECT") for sql in connection.fake_cursor.statements))


    def test_mysql_health_fails_closed_without_vault_password(self):
        profile = DatabaseProfile.create(
            "MySQL", "mysql", host="localhost", port=3306,
            database="weather", username="app",
        )
        result = inspect_database(profile, secrets=None)
        self.assertFalse(result.connected)
        self.assertFalse(result.tracking_table_available)


if __name__ == "__main__":
    unittest.main()
