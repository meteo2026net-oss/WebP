import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from ecmwf_collector.sources.noaa_gefs import (
    GefsRequest, NoaaGefsError, build_gefs_url, download_gefs,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload, self.offset = payload, 0
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size=-1):
        if self.offset >= len(self.payload):
            return b""
        chunk = self.payload[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


class NoaaGefsTests(unittest.TestCase):
    def request(self, **changes):
        values = dict(run_date=date(2026, 11, 6), cycle=12, forecast_hour=6,
                      member="c00", variables=("TMP", "UGRD"),
                      levels=("2_m_above_ground", "10_m_above_ground"))
        values.update(changes)
        return GefsRequest(**values)

    def test_url_contains_member_grid_cycle_and_filters(self):
        url = build_gefs_url(self.request(member="p07"))
        self.assertIn("gep07.t12z.pgrb2a.0p50.f006", url)
        self.assertIn("var_TMP=on", url)
        self.assertIn("lev_10_m_above_ground=on", url)
        self.assertIn("%2Fgefs.20261106%2F12%2Fatmos%2Fpgrb2ap5", url)

    def test_download_writes_member_provenance_and_checksum(self):
        payload = b"GRIB" + b"x" * 128 + b"7777"
        with tempfile.TemporaryDirectory() as tmp:
            path, sidecar = download_gefs(
                self.request(member="p12"), Path(tmp),
                opener=lambda url, timeout: FakeResponse(payload),
            )
            self.assertEqual(path.read_bytes(), payload)
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(meta["model"], "GEFS")
            self.assertEqual(meta["member"], "p12")
            self.assertEqual(meta["resolution"], "0p50")
            self.assertEqual(meta["valid_time"], "2026-11-06T18:00:00Z")
            self.assertEqual(meta["size_bytes"], len(payload))
            self.assertEqual(len(meta["sha256"]), 64)

    def test_rejects_invalid_member_cycle_and_hours(self):
        for changes in (
            {"member": "p31"}, {"member": "c01"}, {"cycle": 3},
            {"forecast_hour": 1}, {"forecast_hour": 195}, {"forecast_hour": 201},
            {"forecast_hour": 385},
        ):
            with self.subTest(changes=changes), self.assertRaises(NoaaGefsError):
                build_gefs_url(self.request(**changes))

    def test_accepts_hour_schedule_boundaries(self):
        for hour in (3, 192, 198, 384):
            with self.subTest(hour=hour):
                self.request(forecast_hour=hour).validate()

    def test_rejects_invalid_variables_and_levels(self):
        with self.assertRaises(NoaaGefsError):
            build_gefs_url(self.request(variables=("TMP&x",)))
        with self.assertRaises(NoaaGefsError):
            build_gefs_url(self.request(levels=("../surface",)))

    def test_invalid_response_is_not_published_and_partial_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(NoaaGefsError):
                download_gefs(
                    self.request(), Path(tmp),
                    opener=lambda url, timeout: FakeResponse(b"not grib"),
                )
            self.assertFalse(list(Path(tmp).glob("*.grib2")))
            self.assertFalse(list(Path(tmp).glob("*.source.json")))
            self.assertFalse(list(Path(tmp).glob("*.part")))


if __name__ == "__main__":
    unittest.main()
