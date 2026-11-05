import sqlite3
import tempfile
from contextlib import closing
import unittest
from pathlib import Path

from ecmwf_collector.state_backup import (
    create_manual_backup,
    ensure_daily_backup,
    restore_sqlite_backup,
)


class StateBackupTests(unittest.TestCase):
    def _database(self, root: Path) -> Path:
        path = root / "state.db"
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                "CREATE TABLE files (remote_path TEXT PRIMARY KEY, status TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO files(remote_path,status) VALUES (?,?)",
                ("/archive/2026/11/sample.grib2", "downloaded"),
            )
            # closing() closes the connection but does not commit its transaction.
            # Commit the fixture explicitly so the backup tests exercise persisted rows.
            db.commit()
        return path

    def test_manual_backup_is_a_verified_consistent_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._database(root)
            backup = create_manual_backup(source, root / "backups")
            with closing(sqlite3.connect(backup)) as db:
                self.assertEqual(
                    db.execute("SELECT remote_path,status FROM files").fetchone(),
                    ("/archive/2026/11/sample.grib2", "downloaded"),
                )
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_daily_backup_is_created_only_once_per_day(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._database(root)
            first = ensure_daily_backup(source, root / "backups")
            with closing(sqlite3.connect(source)) as db:
                db.execute("UPDATE files SET status='validated'")
            second = ensure_daily_backup(source, root / "backups")
            self.assertEqual(first, second)
            with closing(sqlite3.connect(second)) as db:
                self.assertEqual(db.execute("SELECT status FROM files").fetchone()[0], "downloaded")

    def test_daily_backup_is_refreshed_if_existing_snapshot_is_corrupt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._database(root)
            first = ensure_daily_backup(source, root / "backups")
            first.write_bytes(b"not a sqlite database")
            refreshed = ensure_daily_backup(source, root / "backups")
            self.assertNotEqual(first, refreshed)
            with closing(sqlite3.connect(refreshed)) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_missing_database_does_not_create_an_empty_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertIsNone(ensure_daily_backup(root / "missing.db", root / "backups"))
            self.assertFalse((root / "backups").exists())

    def test_manual_rotation_retains_requested_number(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self._database(root)
            backup_dir = root / "backups"
            for _ in range(4):
                create_manual_backup(source, backup_dir, keep=2)
            self.assertEqual(len(list(backup_dir.glob("state-manual-*.db"))), 2)

    def test_restore_creates_safety_copy_before_replacing_current_database(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = self._database(root)
            backup = create_manual_backup(target, root / "backups")
            with closing(sqlite3.connect(target)) as db:
                db.execute("UPDATE files SET status='validated'")
            safety = restore_sqlite_backup(backup, target, root / "backups")
            with closing(sqlite3.connect(target)) as db:
                self.assertEqual(db.execute("SELECT status FROM files").fetchone()[0], "downloaded")
            with closing(sqlite3.connect(safety)) as db:
                self.assertEqual(db.execute("SELECT status FROM files").fetchone()[0], "validated")

    def test_restore_refuses_live_sqlite_wal_sidecar_without_replacing_database(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = self._database(root)
            backup = create_manual_backup(target, root / "backups")
            with closing(sqlite3.connect(target)) as db:
                db.execute("UPDATE files SET status='validated'")
            Path(f"{target}-wal").write_bytes(b"active")
            with self.assertRaisesRegex(RuntimeError, "sidecar"):
                restore_sqlite_backup(backup, target, root / "backups")
            with closing(sqlite3.connect(target)) as db:
                self.assertEqual(db.execute("SELECT status FROM files").fetchone()[0], "validated")

    def test_restore_rejects_invalid_backup_without_touching_current_database(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = self._database(root)
            invalid = root / "invalid.db"
            invalid.write_bytes(b"not sqlite")
            with self.assertRaises(sqlite3.DatabaseError):
                restore_sqlite_backup(invalid, target, root / "backups")
            with closing(sqlite3.connect(target)) as db:
                self.assertEqual(db.execute("SELECT status FROM files").fetchone()[0], "downloaded")

    def test_backup_failure_does_not_replace_original_database(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "state.db"
            source.write_bytes(b"invalid")
            original = source.read_bytes()
            with self.assertRaises(sqlite3.DatabaseError):
                create_manual_backup(source, root / "backups")
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(list((root / "backups").glob("*.db")), [])


if __name__ == "__main__":
    unittest.main()
