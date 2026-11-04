import json
import tempfile
import unittest
from pathlib import Path

from ecmwf_collector.tools.map_manifest import update_manifest


class MapManifestTests(unittest.TestCase):
    def test_updates_same_layer_without_dropping_other_levels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            surface = {
                "source_file": "forecast.grib",
                "variable": "t",
                "valid_time": "2026-11-04T00:00",
                "typeOfLevel": "surface",
                "level": 0,
                "image": "surface.png",
            }
            upper = {**surface, "typeOfLevel": "isobaricInhPa", "level": 850, "image": "850.png"}
            update_manifest(root, [surface, upper])
            replacement = {**surface, "image": "surface_new.png"}
            path = update_manifest(root, [replacement])
            manifest = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["layers"]), 2)
            self.assertIn("surface_new.png", [x["image"] for x in manifest["layers"]])
            self.assertIn("850.png", [x["image"] for x in manifest["layers"]])


if __name__ == "__main__":
    unittest.main()
