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
        with sqlite3.connect(self.path) as db:
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
        before = self.path.read_bytes()
        result = inspect_database(self._profile(), secrets=None)
        self.assertTrue(result.connected)
        self.assertTrue(result.tracking_table_available)
        self.assertEqual(result.tracked_files, 3)
        self.assertEqual(result.completed_files, 1)
        self.assertEqual(result.failed_files, 1)
        self.assertEqual(result.remote_bytes, 600)
        self.assertEqual(result.local_bytes, 120)
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

    def test_mysql_profile_is_explicitly_not_supported_yet(self):
        profile = DatabaseProfile.create(
            "MySQL", "mysql", host="localhost", port=3306,
            database="weather", username="app",
        )
        result = inspect_database(profile, secrets=None)
        self.assertFalse(result.connected)
        self.assertIn("غير متاح", result.message)


if __name__ == "__main__":
    unittest.main()
