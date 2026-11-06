import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from ecmwf_collector.sources.noaa_gefs import (
    GefsRequest, NoaaGefsError, build_gefs_url, download_gefs, download_gefs_ensemble,\n    write_gefs_ensemble_manifest,
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


    def test_failed_metadata_write_removes_unpaired_grib(self):
        payload = b"GRIB" + b"x" * 128 + b"7777"
        with tempfile.TemporaryDirectory() as tmp:
            real_replace = os.replace
            def fail_metadata_replace(source, destination):
                if str(destination).endswith(".source.json"):
                    raise OSError("disk full")
                return real_replace(source, destination)
            with patch("ecmwf_collector.sources.noaa_gefs.os.replace", side_effect=fail_metadata_replace):
                with self.assertRaises(OSError):
                    download_gefs(
                        self.request(), Path(tmp),
                        opener=lambda url, timeout: FakeResponse(payload),
                    )
            self.assertFalse(list(Path(tmp).glob("*.grib2")))
            self.assertFalse(list(Path(tmp).glob("*.part")))

    def test_batch_download_records_success_and_member_failure(self):
        payload = b"GRIB" + b"x" * 128 + b"7777"
        def opener(url, timeout):
            if "gep02." in url:
                raise OSError("simulated member outage")
            return FakeResponse(payload)
        with tempfile.TemporaryDirectory() as tmp:
            completed, failed = download_gefs_ensemble(
                self.request(), Path(tmp), members=("c00", "p01", "p02"), opener=opener
            )
            self.assertEqual([item[0] for item in completed], ["c00", "p01"])
            self.assertEqual([item[0] for item in failed], ["p02"])
            self.assertEqual(len(list(Path(tmp).glob("*.grib2"))), 2)
            self.assertEqual(len(list(Path(tmp).glob("*.source.json"))), 2)

    def test_ensemble_manifest_records_partial_batch_without_claiming_statistics(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = self.request()
            completed = [("c00", Path("c00.grib2"), Path("c00.source.json"))]
            failed = [("p01", "network unavailable")]
            manifest = write_gefs_ensemble_manifest(
                request, Path(tmp), completed, failed, requested_members=("c00", "p01")
            )
            data = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(data["summary"], {"requested": 2, "completed": 1, "failed": 1})
            self.assertEqual(data["completed_members"][0]["member"], "c00")
            self.assertEqual(data["failed_members"][0]["member"], "p01")
            self.assertIn("does not contain ensemble statistics", data["note"])
            self.assertFalse(list(Path(tmp).glob("*.part")))

    def test_batch_rejects_duplicate_members_before_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(NoaaGefsError):
                download_gefs_ensemble(
                    self.request(), Path(tmp), members=("c00", "c00"),
                    opener=lambda url, timeout: FakeResponse(b"GRIB" + b"x" * 128 + b"7777"),
                )
            self.assertEqual(list(Path(tmp).iterdir()), [])

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
