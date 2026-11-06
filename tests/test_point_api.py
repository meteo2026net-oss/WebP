"""Tests for the map server's manifest-backed scientific point API."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

import serve_map


class MapPointApiTests(unittest.TestCase):
    def _handler(self):
        handler = object.__new__(serve_map.MapOnlyHandler)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = Mock()
        return handler

    def _write_manifest(self, root, data_file="field.npz"):
        (root / "manifest.json").write_text(
            json.dumps({"layers": [{
                "image": "field.png",
                "data_file": data_file,
                "variable": "t2m",
                "long_name": "2 metre temperature",
                "units": "K",
                "valid_time": "2026-11-05T00:00:00",
            }]}),
            encoding="utf-8",
        )

    def test_returns_scientific_bilinear_value_for_manifest_layer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._write_manifest(root)
            np.savez_compressed(
                root / "field.npz",
                values=np.array([[0, 10], [20, 30]], dtype=np.float32),
                latitudes=np.array([1, 0], dtype=np.float64),
                longitudes=np.array([10, 11], dtype=np.float64),
            )
            handler = self._handler()
            with patch.object(serve_map, "MAP_DATA", root):
                handler._point_query({
                    "image": ["field.png"], "lat": ["0.5"],
                    "lon": ["10.5"], "method": ["bilinear"],
                })
            self.assertEqual(handler.send_response.call_args.args[0], 200)
            payload = json.loads(handler.wfile.write.call_args.args[0])
            self.assertTrue(payload["valid"])
            self.assertAlmostEqual(payload["value"], 15.0)
            self.assertEqual(payload["units"], "K")
            self.assertEqual(payload["variable"], "t2m")

    def test_rejects_layer_not_listed_in_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._write_manifest(root)
            handler = self._handler()
            with patch.object(serve_map, "MAP_DATA", root):
                handler._point_query({
                    "image": ["unlisted.png"], "lat": ["0"],
                    "lon": ["0"],
                })
            self.assertEqual(handler.send_response.call_args.args[0], 404)
            payload = json.loads(handler.wfile.write.call_args.args[0])
            self.assertEqual(payload["error"], "Layer not found in manifest.")

    def test_rejects_manifest_data_path_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._write_manifest(root, "../outside.npz")
            handler = self._handler()
            with patch.object(serve_map, "MAP_DATA", root):
                handler._point_query({
                    "image": ["field.png"], "lat": ["0"],
                    "lon": ["0"],
                })
            self.assertEqual(handler.send_response.call_args.args[0], 404)
            payload = json.loads(handler.wfile.write.call_args.args[0])
            self.assertEqual(payload["error"], "This layer has no point-query data.")

    def test_rejects_unsupported_sampling_method_as_client_error(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self._write_manifest(root)
            np.savez_compressed(
                root / "field.npz",
                values=np.ones((2, 2), dtype=np.float32),
                latitudes=np.array([1, 0], dtype=np.float64),
                longitudes=np.array([10, 11], dtype=np.float64),
            )
            handler = self._handler()
            with patch.object(serve_map, "MAP_DATA", root):
                handler._point_query({
                    "image": ["field.png"], "lat": ["0.5"],
                    "lon": ["10.5"], "method": ["cubic"],
                })
            self.assertEqual(handler.send_response.call_args.args[0], 400)
            payload = json.loads(handler.wfile.write.call_args.args[0])
            self.assertIn("Sampling method", payload["error"])


if __name__ == "__main__":
    unittest.main()
