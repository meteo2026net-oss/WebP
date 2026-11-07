"""Tests for GEFS member provenance grouping before GRIB decoding."""
import json
import tempfile
import unittest
from pathlib import Path
from ecmwf_collector.gefs_grib import GefsMemberMetadataError, load_gefs_member_metadata, validate_gefs_member_metadata

def metadata(member="c00", **overrides):
    value = {"source": "NOAA/NCEP NOMADS", "model": "GEFS", "member": member,
             "run": "20261107T00:00:00Z", "forecast_hour": 24,
             "valid_time": "2026-11-08T00:00:00Z", "variables": ["TMP", "UGRD"],
             "levels": ["2_m_above_ground", "10_m_above_ground"], "resolution": "0p50",
             "file_name": f"gefs_{member}.grib2"}
    value.update(overrides)
    return value

class GefsMetadataGateTests(unittest.TestCase):
    def test_accepts_members_with_same_forecast_definition(self):
        result = validate_gefs_member_metadata({"c00": metadata("c00"), "p01": metadata("p01", variables=["UGRD", "TMP"])})
        self.assertEqual(set(result), {"c00", "p01"})

    def test_rejects_different_run_or_valid_time(self):
        with self.assertRaisesRegex(GefsMemberMetadataError, "run"):
            validate_gefs_member_metadata({"c00": metadata("c00"), "p01": metadata("p01", run="20261107T06:00:00Z")})

    def test_rejects_different_variable_or_level_definition(self):
        with self.assertRaisesRegex(GefsMemberMetadataError, "variables"):
            validate_gefs_member_metadata({"c00": metadata("c00"), "p01": metadata("p01", variables=["TMP"])})

    def test_rejects_too_few_or_invalid_members(self):
        with self.assertRaises(GefsMemberMetadataError):
            validate_gefs_member_metadata({"c00": metadata("c00")})
        with self.assertRaises(GefsMemberMetadataError):
            validate_gefs_member_metadata({"c00": metadata("c00"), "p31": metadata("p31")})

    def test_loads_matching_sidecars_and_rejects_filename_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for member in ("c00", "p01"):
                grib = root / f"gefs_{member}.grib2"
                grib.write_bytes(b"GRIB" + b"x" * 12 + b"7777")
                (root / f"gefs_{member}.source.json").write_text(json.dumps(metadata(member)), encoding="utf-8")
                paths.append(grib)
            self.assertEqual(set(load_gefs_member_metadata(paths)), {"c00", "p01"})
            sidecar = root / "gefs_p01.source.json"
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            payload["file_name"] = "different.grib2"
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(GefsMemberMetadataError, "filename"):
                load_gefs_member_metadata(paths)

if __name__ == "__main__":
    unittest.main()