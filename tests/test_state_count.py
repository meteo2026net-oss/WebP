import unittest
from pathlib import Path

from ecmwf_collector.state import StateStore


class SQLiteStateCountTests(unittest.TestCase):
    def test_count_tracks_insertions_without_loading_all_records(self):
        store = StateStore(Path(":memory:"))
        try:
            self.assertEqual(store.count(), 0)
            store.upsert("/2026/11/05/file-a.grib", status="downloaded")
            store.upsert("/2026/11/05/file-b.grib", status="pending")
            self.assertEqual(store.count(), 2)
            store.upsert("/2026/11/05/file-a.grib", status="verified")
            self.assertEqual(store.count(), 2)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
