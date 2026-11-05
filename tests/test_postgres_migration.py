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


if __name__ == "__main__":
    unittest.main()
