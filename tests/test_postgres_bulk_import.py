import threading
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from ecmwf_collector.state import FileRecord
from ecmwf_collector.postgres_state import PostgresStateStore


def record(path, *, status="downloaded", digest="abc"):
    return FileRecord(path, 100, f"C:/data/{path.rsplit('/', 1)[-1]}", status,
                      100, digest, "GRIB", "valid", "2026-11-06T00:00:00+00:00",
                      1, None, "2026-11-06T00:00:00+00:00")


class Cursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class ImportConnection:
    def __init__(self, existing, inserted_paths):
        self.existing = existing
        self.inserted_paths = inserted_paths
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, params))
        if sql.startswith("INSERT"):
            return Cursor([(path,) for path in self.inserted_paths])
        if "ANY(%s)" in sql:
            return Cursor([self.existing[path] for path in params[0] if path in self.existing])
        raise AssertionError(f"Unexpected SQL: {sql}")


class PostgresBulkImportTests(unittest.TestCase):
    def make_store(self, connection):
        store = object.__new__(PostgresStateStore)
        store._lock = threading.RLock()
        store._connect = lambda: connection
        return store

    def test_import_uses_one_insert_and_one_verification_query_per_batch(self):
        first, second = record("/a.grib"), record("/b.grib", digest="def")
        rows = {
            first.remote_path: tuple(first.__dict__.values()),
            second.remote_path: tuple(second.__dict__.values()),
        }
        connection = ImportConnection(rows, [first.remote_path])
        with patch.object(PostgresStateStore, "_connect", connection):
            store = self.make_store(connection)
            self.assertEqual(store.import_records([first, second]), 1)
        self.assertEqual(len(connection.statements), 2)
        self.assertIn("ON CONFLICT (remote_path) DO NOTHING RETURNING remote_path",
                      connection.statements[0][0])
        self.assertIn("WHERE remote_path = ANY(%s)", connection.statements[1][0])
        self.assertEqual(len(connection.statements[0][1]), 24)

    def test_import_rejects_different_existing_target_record(self):
        source = record("/a.grib")
        changed = record("/a.grib", status="failed")
        connection = ImportConnection({source.remote_path: tuple(changed.__dict__.values())}, [])
        store = self.make_store(connection)
        with self.assertRaisesRegex(RuntimeError, "target row differs"):
            store.import_records([source])

    def test_import_rejects_conflicting_duplicate_source_before_writing(self):
        first = record("/a.grib")
        duplicate = record("/a.grib", digest="different")
        connection = ImportConnection({}, [])
        store = self.make_store(connection)
        with self.assertRaisesRegex(RuntimeError, "Conflicting source records"):
            store.import_records([first, duplicate])
        self.assertEqual(connection.statements, [])

    def test_empty_import_performs_no_database_work(self):
        connection = ImportConnection({}, [])
        store = self.make_store(connection)
        self.assertEqual(store.import_records([]), 0)
        self.assertEqual(connection.statements, [])


if __name__ == "__main__":
    unittest.main()
