import unittest
from datetime import date, datetime, timezone

from ecmwf_collector.connection import ConnectionSettings, open_session
from ecmwf_collector.listing import (RemoteEntry, filter_day_folders, human_size, list_directory,
                                     parse_day_folder, parse_mlsd_time, sort_day_folders)
from tests.fakes import FakeServerState, make_factory

TREE = {
    "/": [("07-03-2026 00:00", {"type": "dir"}), ("08-03-2026 00:00", {"type": "dir"}),
          ("weird", {"type": "dir"}), (".", {"type": "cdir"}), ("..", {"type": "pdir"})],
    "/08-03-2026 00:00": [
        ("a.grib2", {"type": "file", "size": "1024", "modify": "20260308060501"}),
        ("empty.grib2", {"type": "file", "size": "0", "modify": "20260308060501"}),
        ("bad.bin", {"type": "file", "size": "abc", "modify": "garbage"}),
    ],
    "/empty": [],
}


def session(state):
    s = ConnectionSettings("h", 21, "u", "secret-pass", protocol="ftps", timeout=5, max_retries=1)
    return open_session(s, make_factory(state), lambda _: None)


class ListingTests(unittest.TestCase):
    def test_mlsd_listing_with_spaces_skips_cdir_pdir(self):
        with session(FakeServerState(tree=TREE)) as s:
            names = [e.name for e in list_directory(s, "/")]
        self.assertEqual(sorted(names), ["07-03-2026 00:00", "08-03-2026 00:00", "weird"])

    def test_file_metadata_and_utc(self):
        with session(FakeServerState(tree=TREE)) as s:
            files = {e.name: e for e in list_directory(s, "/08-03-2026 00:00")}
        self.assertEqual(files["a.grib2"].size, 1024)
        self.assertEqual(files["a.grib2"].modified, datetime(2026, 3, 8, 6, 5, 1, tzinfo=timezone.utc))
        self.assertEqual(files["empty.grib2"].size, 0)

    def test_corrupt_facts_do_not_crash_or_invent(self):
        with session(FakeServerState(tree=TREE)) as s:
            f = {e.name: e for e in list_directory(s, "/08-03-2026 00:00")}["bad.bin"]
        self.assertIsNone(f.size)
        self.assertIsNone(f.modified)

    def test_empty_directory(self):
        with session(FakeServerState(tree=TREE)) as s:
            self.assertEqual(list_directory(s, "/empty"), [])

    def test_fallback_to_list(self):
        lines = {"/": [
            "drwxr-xr-x   2 ftp ftp      4096 Mar  8 00:00 08-03-2026 00:00",
            "-rw-r--r--   1 ftp ftp   1048576 Mar  8 06:05 data file.grib2",
            "garbage line"]}
        st = FakeServerState(mlsd_supported=False, list_lines=lines)
        with session(st) as s:
            entries = list_directory(s, "/")
        by = {e.name: e for e in entries}
        self.assertTrue(by["08-03-2026 00:00"].is_dir)
        self.assertEqual(by["data file.grib2"].size, 1048576)
        self.assertIsNone(by["data file.grib2"].modified)  # لا يُخمَّن الوقت

    def test_parse_helpers(self):
        self.assertEqual(parse_day_folder("07-03-2026 00:00"), datetime(2026, 3, 7, tzinfo=timezone.utc))
        self.assertEqual(parse_day_folder("20261027"), datetime(2026, 10, 27, tzinfo=timezone.utc))
        self.assertIsNone(parse_day_folder("weird"))
        self.assertIsNone(parse_day_folder("20261340"))
        self.assertIsNone(parse_mlsd_time("nope"))
        self.assertEqual(parse_mlsd_time("20260308060501.123").second, 1)

    def test_sort_and_filter(self):
        es = [RemoteEntry(n, "/" + n, True) for n in ("07-03-2026 00:00", "weird", "08-03-2026 00:00")]
        self.assertEqual([e.name for e in sort_day_folders(es)], ["08-03-2026 00:00", "07-03-2026 00:00", "weird"])
        kept = filter_day_folders(es, date(2026, 3, 8), date(2026, 3, 8))
        self.assertIn("08-03-2026 00:00", [e.name for e in kept])
        self.assertNotIn("07-03-2026 00:00", [e.name for e in kept])
        self.assertIn("weird", [e.name for e in kept])  # لا يُخفى مجلد غير مفهوم

    def test_real_server_folder_names(self):
        es = [RemoteEntry(n, "/" + n, True) for n in ("20261024", "20261027", "20261025")]
        self.assertEqual([e.name for e in sort_day_folders(es)], ["20261027", "20261025", "20261024"])
        kept = filter_day_folders(es, date(2026, 10, 25), date(2026, 10, 26))
        self.assertEqual([e.name for e in kept], ["20261025"])

    def test_human_size(self):
        self.assertEqual(human_size(None), "—")
        self.assertEqual(human_size(512), "512 B")
        self.assertEqual(human_size(1048576), "1.0 MB")


if __name__ == "__main__":
    unittest.main()
