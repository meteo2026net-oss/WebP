import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from ecmwf_collector.fileinspect import inspect_file
from ecmwf_collector.naming import parse_product_name
from ecmwf_collector.state import StateStore

UTC = timezone.utc


def grib2(body=100):
    return b"GRIB\x00\x00\x00\x02" + (16 + body + 4).to_bytes(8, "big") + b"x" * body + b"7777"


def bufr(body=20):
    return b"BUFR" + (8 + body + 4).to_bytes(3, "big") + b"\x04" + b"y" * body + b"7777"


class NamingTests(unittest.TestCase):
    def test_real_names_from_server(self):
        p = parse_product_name("FMD10270000102703001", date(2026, 10, 27))
        self.assertEqual((p.kind, p.step_hours), ("FM", 3))
        self.assertEqual(p.base, datetime(2026, 10, 27, 0, 0, tzinfo=UTC))
        self.assertFalse(p.step0_marker)

    def test_step_zero_marker(self):
        p = parse_product_name("FMD10270000102700011", date(2026, 10, 27))
        self.assertTrue(p.step0_marker)
        self.assertEqual(p.step_hours, 0)
        self.assertEqual(p.valid, p.base)

    def test_analysis_and_12z(self):
        a = parse_product_name("AND10271200102712001", date(2026, 10, 27))
        self.assertEqual((a.kind, a.step_hours, a.base.hour), ("AN", 0, 12))

    def test_doc_example(self):
        p = parse_product_name("FPD05110000051412001", date(2026, 5, 11))
        self.assertEqual((p.kind, p.step_hours), ("FP", 84))

    def test_year_rollover(self):
        p = parse_product_name("FSD12310000010106001", date(2026, 12, 31))
        self.assertEqual(p.valid, datetime(2027, 1, 1, 6, tzinfo=UTC))
        self.assertEqual(p.step_hours, 30)
        q = parse_product_name("FSD12310000123106001", date(2027, 1, 1))
        self.assertEqual(q.base.year, 2026)

    def test_unparseable_returns_none(self):
        for bad in ("weird.txt", "FMD1027", "XXD10270000102703001", "FMD13400000102703001"):
            self.assertIsNone(parse_product_name(bad, date(2026, 10, 27)), bad)


class InspectTests(unittest.TestCase):
    def check(self, data):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "f"
            p.write_bytes(data)
            return inspect_file(p)

    def test_valid_grib2_multi_message(self):
        r = self.check(grib2() + grib2(300))
        self.assertEqual((r.kind, r.verdict, r.messages), ("grib2", "ok", 2))

    def test_truncated(self):
        r = self.check(grib2()[:-10])
        self.assertEqual(r.verdict, "corrupt")

    def test_missing_end_marker(self):
        r = self.check(grib2()[:-4] + b"XXXX")
        self.assertEqual(r.verdict, "corrupt")

    def test_trailing_garbage(self):
        self.assertEqual(self.check(grib2() + b"junk").verdict, "corrupt")

    def test_empty(self):
        r = self.check(b"")
        self.assertEqual((r.kind, r.verdict), ("empty", "corrupt"))

    def test_bufr(self):
        r = self.check(bufr())
        self.assertEqual((r.kind, r.verdict), ("bufr", "ok"))

    def test_unknown_is_unverified_not_corrupt(self):
        r = self.check(b"hello,world\n1,2\n")
        self.assertEqual((r.detected_type, r.verdict), ("unknown", "unverified"))


class StateTests(unittest.TestCase):
    def test_upsert_get_and_csv(self):
        with tempfile.TemporaryDirectory() as d:
            s = StateStore(Path(d) / "s.db")
            s.upsert("/a/b", status="complete", remote_size=5, sha256="ab", downloaded_at="2026-10-28T00:00:00+00:00")
            s.upsert("/a/b", local_size=5)
            s.bump_attempts("/a/b")
            r = s.get("/a/b")
            self.assertEqual((r.status, r.local_size, r.attempts), ("complete", 5, 1))
            self.assertIsNone(s.get("/nope"))
            self.assertEqual(s.export_csv(Path(d) / "m.csv"), 1)
            self.assertIn("sha256", (Path(d) / "m.csv").read_text(encoding="utf-8-sig"))
            with self.assertRaises(ValueError):
                s.upsert("/a/b", password="x")
            s.close()

    def test_persists_across_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.db"
            s = StateStore(p)
            s.upsert("/x", status="failed", last_error="boom")
            s.close()
            reopened = StateStore(p)
            try:
                self.assertEqual(reopened.get("/x").last_error, "boom")
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
