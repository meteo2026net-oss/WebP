import json
import tempfile
import unittest
from pathlib import Path

from ecmwf_collector.tools.grib_to_map import _load_source_report


class ECMWFMapAttributionTests(unittest.TestCase):
    def test_loads_required_ecmwf_attribution(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "forecast.grib2"
            report = {
                "source": "ecmwf_open_data",
                "source_provider": "Amazon Web Services Open Data mirror",
                "attribution": {
                    "required_text": "This service is based on data and products of ECMWF.",
                    "license": "CC BY 4.0",
                },
            }
            source.with_suffix(".grib2.source.json").write_text(
                json.dumps(report), encoding="utf-8"
            )
            loaded = _load_source_report(source)
            self.assertEqual(loaded["attribution"]["license"], "CC BY 4.0")
            self.assertEqual(loaded["source_provider"], report["source_provider"])

    def test_rejects_ecmwf_sidecar_without_required_attribution(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "forecast.grib2"
            source.with_suffix(".grib2.source.json").write_text(
                json.dumps({"source": "ecmwf_open_data"}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "missing required attribution"):
                _load_source_report(source)

    def test_rejects_corrupt_source_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "forecast.grib2"
            source.with_suffix(".grib2.source.json").write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unreadable"):
                _load_source_report(source)

    def test_no_sidecar_is_valid_for_legacy_wmo_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "legacy-wmo.grib2"
            self.assertIsNone(_load_source_report(source))


if __name__ == "__main__":
    unittest.main()
