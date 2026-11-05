import json
import tempfile
import unittest
from pathlib import Path

from ecmwf_collector.tools.map_manifest import update_manifest


class MapManifestTests(unittest.TestCase):
    def test_invalid_json_manifest_is_preserved_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "manifest.json"
            original = '{"version": 1, "layers": ['
            path.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not valid JSON"):
                update_manifest(root, [{"variable": "t", "image": "new.png"}])
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_invalid_utf8_manifest_is_preserved_and_reports_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "manifest.json"
            original = b'{"version": 1, "layers": [\\xff]}'
            path.write_bytes(original)
            with self.assertRaisesRegex(ValueError, "not valid UTF-8"):
                update_manifest(root, [{"variable": "t", "image": "new.png"}])
            self.assertEqual(path.read_bytes(), original)

    def test_invalid_manifest_structure_is_preserved(self):
        for payload in ('[]', '{"version": 1}', '{"version": 1, "layers": [null]}'):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / "manifest.json"
                path.write_text(payload, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "invalid structure|non-object layer"):
                    update_manifest(root, [{"variable": "t", "image": "new.png"}])
                self.assertEqual(path.read_text(encoding="utf-8"), payload)

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

    def test_keeps_distinct_grib_groups_and_ensemble_slices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            common = {
                "source_id": "same-source",
                "source_file": "ensemble.grib",
                "variable": "t",
                "valid_time": "2026-11-04T00:00",
                "typeOfLevel": "isobaricInhPa",
                "level": 850,
                "step": "0 hours",
                "units": "K",
            }
            products = [
                {**common, "group_index": 0, "extra_coordinates": {"number": 0}, "image": "member0.png"},
                {**common, "group_index": 0, "extra_coordinates": {"number": 1}, "image": "member1.png"},
                {**common, "group_index": 1, "extra_coordinates": {"number": 0}, "image": "group1.png"},
            ]
            path = update_manifest(root, products)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["layers"]), 3)
            self.assertEqual(
                {item["image"] for item in manifest["layers"]},
                {"member0.png", "member1.png", "group1.png"},
            )

    def test_accepts_array_valued_time_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layer = {"source_file": "wind.grib", "source_id": "abc", "variable": "wind_speed",
                     "valid_time": ["2026-11-04T00:00", "2026-11-04T06:00"], "step": [0, 6], "image": "wind.png"}
            path = update_manifest(root, [layer])
            manifest = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["layers"][0]["step"], [0, 6])


    def test_keeps_same_source_layer_in_distinct_display_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = {
                "source_id": "same-source",
                "source_file": "forecast.grib2",
                "variable": "t2m",
                "valid_time": "2026-11-04T00:00",
                "units": "K",
                "display_conversion_applied": True,
            }
            products = [
                {**source, "display_units": "K", "image": "temperature-k.png"},
                {**source, "display_units": "°C", "image": "temperature-c.png"},
            ]
            path = update_manifest(root, products)
            manifest = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["layers"]), 2)
            self.assertEqual(
                {item["display_units"] for item in manifest["layers"]},
                {"K", "°C"},
            )


if __name__ == "__main__":
    unittest.main()
