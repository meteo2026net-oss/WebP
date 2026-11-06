import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from ecmwf_collector.sources.noaa_gfs import (
    GfsRequest, NoaaGfsError, build_gfs_url, download_gfs,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.offset = 0
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


class NoaaGfsTests(unittest.TestCase):
    def request(self, **changes):
        values = dict(run_date=date(2026, 11, 6), cycle=12, forecast_hour=6,
                      variables=("TMP", "UGRD"), levels=("2_m_above_ground", "10_m_above_ground"))
        values.update(changes)
        return GfsRequest(**values)

    def test_url_encodes_cycle_file_variables_and_levels(self):
        url = build_gfs_url(self.request())
        self.assertIn("gfs.t12z.pgrb2.0p25.f006", url)
        self.assertIn("var_TMP=on", url)
        self.assertIn("var_UGRD=on", url)
        self.assertIn("lev_2_m_above_ground=on", url)
        self.assertIn("%2Fgfs.20261106%2F12%2Fatmos", url)

    def test_download_saves_verified_grib_and_sidecar(self):
        payload = b"GRIB" + b"x" * 128 + b"7777"
        with tempfile.TemporaryDirectory() as tmp:
            path, sidecar = download_gfs(self.request(), Path(tmp),
                                         opener=lambda url, timeout: FakeResponse(payload))
            self.assertEqual(path.read_bytes(), payload)
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(data["source"], "NOAA/NCEP NOMADS")
            self.assertEqual(data["model"], "GFS")
            self.assertEqual(data["run"], "20261106T12:00:00Z")
            self.assertEqual(data["valid_time"], "2026-11-06T18:00:00Z")
            self.assertEqual(data["variables"], ["TMP", "UGRD"])
            self.assertEqual(data["size_bytes"], len(payload))
            self.assertEqual(len(data["sha256"]), 64)
            self.assertFalse((Path(tmp) / (path.name + ".part")).exists())

    def test_rejects_invalid_cycle_and_forecast_step(self):
        with self.assertRaises(NoaaGfsError):
            build_gfs_url(self.request(cycle=3))
        with self.assertRaises(NoaaGfsError):
            build_gfs_url(self.request(forecast_hour=121))

    def test_rejects_untrusted_variable_or_level(self):
        with self.assertRaises(NoaaGfsError):
            build_gfs_url(self.request(variables=("TMP&evil",)))
        with self.assertRaises(NoaaGfsError):
            build_gfs_url(self.request(levels=("../surface",)))

    def test_invalid_payload_is_not_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(NoaaGfsError):
                download_gfs(self.request(), Path(tmp),
                             opener=lambda url, timeout: FakeResponse(b"not a grib"))
            self.assertFalse(list(Path(tmp).glob("*.grib2")))
            self.assertFalse(list(Path(tmp).glob("*.source.json")))


if __name__ == "__main__":
    unittest.main()
