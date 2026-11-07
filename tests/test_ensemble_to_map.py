"""Tests for GEFS ensemble map-layer export."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from ecmwf_collector.tools.ensemble_to_map import write_gefs_ensemble_map_products


class GefsEnsembleMapTests(unittest.TestCase):
    def _inputs(self):
        field = {
            "latitude": np.array([52.0, 51.0]),
            "longitude": np.array([30.0, 31.0]),
            "units": "K",
            "initialization_time": "2026-11-07T00:00:00Z",
            "valid_time": "2026-11-08T00:00:00Z",
            "forecast_hour": 24,
            "members": ["c00", "p01"],
            "short_name": "2t",
            "type_of_level": "heightAboveGround",
            "level": 2,
        }
        stats = {
            "mean": np.array([[270.0, 271.0], [272.0, 273.0]]),
            "spread": np.array([[1.0, 1.5], [2.0, 2.5]]),
            "member_count": np.full((2, 2), 2),
            "probability_exceeding_threshold_percent": np.array([[0.0, 50.0], [50.0, 100.0]]),
            "threshold": 271.0,
        }
        return stats, field

    def test_writes_mean_spread_probability_png_npz_and_manifest(self):
        stats, field = self._inputs()
        with tempfile.TemporaryDirectory() as tmp:
            products, manifest_path = write_gefs_ensemble_map_products(
                stats, field, tmp, source_file="two-members.grib2"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(products), 3)
            self.assertEqual(len(manifest["layers"]), 3)
            probability = next(item for item in products if item["variable"] == "exceedance_probability")
            self.assertEqual(probability["threshold"], 271.0)
            self.assertEqual(probability["threshold_comparison"], "strictly greater than")
            self.assertEqual(
                {item["variable"] for item in products},
                {"ensemble_mean", "ensemble_spread", "exceedance_probability"},
            )
            for item in products:
                with Image.open(Path(tmp) / item["image"]) as image:
                    self.assertEqual(image.mode, "RGBA")
                with np.load(Path(tmp) / item["data_file"], allow_pickle=False) as data:
                    self.assertIn("values", data.files)
                    self.assertEqual(data["values"].shape, (2, 2))

    def test_rejects_statistics_that_do_not_match_geolocation(self):
        stats, field = self._inputs()
        stats["mean"] = np.ones((3, 3))
        stats["spread"] = np.ones((3, 3))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "does not match grid"):
                write_gefs_ensemble_map_products(stats, field, tmp)


if __name__ == "__main__":
    unittest.main()
