import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from ecmwf_collector.gui.forecast_workspace import ForecastCatalogWidget


class ForecastCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_noaa_sidecar_fields_are_indexed_and_grib_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grib = root / "gfs_20261107_00z_f006_0p25.grib2"
            grib.write_bytes(b"GRIB" + b"x" * 32 + b"7777")
            sidecar = root / "gfs_20261107_00z_f006_0p25.source.json"
            sidecar.write_text(json.dumps({
                "source": "NOAA/NCEP NOMADS",
                "model": "GFS",
                "run": "20261107T00:00:00Z",
                "valid_time": "2026-11-07T06:00:00Z",
                "forecast_hour": 6,
                "variables": ["TMP", "UGRD"],
                "file_name": grib.name,
                "integrity": "GRIB2 framing checked; SHA-256 recorded",
            }), encoding="utf-8")

            widget = ForecastCatalogWidget(root)
            records = widget._records()
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record["source"], "NOAA/NCEP NOMADS")
            self.assertEqual(record["model"], "GFS")
            self.assertEqual(record["run"], "20261107T00:00:00Z")
            self.assertEqual(record["valid"], "2026-11-07T06:00:00Z")
            self.assertEqual(record["step"], "6 ساعة")
            self.assertEqual(record["params"], "TMP, UGRD")
            self.assertEqual(record["file"], grib.name)
            self.assertEqual(record["member"], "—")
            widget.close()

    def test_gefs_ensemble_manifest_is_indexed_as_group_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "gefs_20261107_00z_f024_ensemble.manifest.json"
            manifest.write_text(json.dumps({
                "source": "NOAA/NCEP NOMADS",
                "model": "GEFS",
                "run": "20261107T00:00:00Z",
                "valid_time": "2026-11-08T00:00:00Z",
                "forecast_hour": 24,
                "variables": ["TMP", "UGRD"],
                "requested_members": ["c00", "p01", "p02"],
                "completed_members": [
                    {"member": "c00", "file_name": "c00.grib2"},
                    {"member": "p01", "file_name": "p01.grib2"},
                ],
                "failed_members": [{"member": "p02", "error": "network unavailable"}],
                "summary": {"requested": 3, "completed": 2, "failed": 1},
            }), encoding="utf-8")

            widget = ForecastCatalogWidget(root)
            records = widget._records()
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record["source"], "NOAA/NCEP NOMADS")
            self.assertEqual(record["model"], "GEFS — ملخص مجموعة")
            self.assertEqual(record["member"], "2/3 أعضاء")
            self.assertEqual(record["run"], "20261107T00:00:00Z")
            self.assertEqual(record["valid"], "2026-11-08T00:00:00Z")
            self.assertEqual(record["step"], "24 ساعة")
            self.assertEqual(record["params"], "TMP, UGRD")
            self.assertIn("2 ناجح | 1 فاشل", record["integrity"])
            self.assertIn("ليس فحصاً علمياً", record["integrity"])
            self.assertEqual(record["file"], manifest.name)
            widget.close()

    def test_gefs_member_is_visible_in_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grib = root / "gefs_20261107_00z_p07_f024_0p50.grib2"
            grib.write_bytes(b"GRIB" + b"x" * 32 + b"7777")
            sidecar = root / "gefs_20261107_00z_p07_f024_0p50.source.json"
            sidecar.write_text(json.dumps({
                "source": "NOAA/NCEP NOMADS",
                "model": "GEFS",
                "member": "p07",
                "run": "20261107T00:00:00Z",
                "valid_time": "2026-11-08T00:00:00Z",
                "forecast_hour": 24,
                "variables": ["TMP"],
                "file_name": grib.name,
                "integrity": "GRIB2 framing checked; SHA-256 recorded",
            }), encoding="utf-8")

            widget = ForecastCatalogWidget(root)
            records = widget._records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["model"], "GEFS")
            self.assertEqual(records[0]["member"], "p07")
            self.assertEqual(records[0]["step"], "24 ساعة")
            widget.close()


if __name__ == "__main__":
    unittest.main()
