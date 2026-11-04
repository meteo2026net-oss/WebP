import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from webp_to_npz import decode_component, decode_texture


class WindTextureTests(unittest.TestCase):
    def test_decode_component_endpoints_and_midpoint(self):
        decoded = decode_component(np.array([0, 127.5, 255]), -100.0, 100.0)
        np.testing.assert_allclose(decoded, [-100.0, 0.0, 100.0], atol=0.4)

    def test_decode_rejects_invalid_range(self):
        with self.assertRaises(ValueError):
            decode_component(np.array([10]), 5.0, 5.0)

    def test_texture_round_trip_and_missing_mask(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            webp = root / "wind.webp"
            sidecar = root / "wind.json"
            rgb = np.array([
                [[128, 128, 255], [0, 255, 0]],
                [[64, 192, 255], [255, 0, 255]],
            ], dtype=np.uint8)
            Image.fromarray(rgb, mode="RGB").save(webp, format="WEBP", lossless=True)
            sidecar.write_text(json.dumps({
                "encoding_version": 1,
                "decode": {"vmin": -100, "vmax": 100},
                "grid": {"width": 2, "height": 2}
            }), encoding="utf-8")

            u, v, valid, _ = decode_texture(webp, sidecar)
            self.assertEqual(valid.tolist(), [[True, False], [True, True]])
            self.assertTrue(np.isnan(u[0, 1]))
            self.assertTrue(np.isnan(v[0, 1]))
            self.assertAlmostEqual(float(u[0, 0]), -100 + 128 / 255 * 200, places=4)
            self.assertAlmostEqual(float(v[1, 0]), -100 + 192 / 255 * 200, places=4)

    def test_rejects_image_metadata_dimension_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            webp = root / "wind.webp"
            sidecar = root / "wind.json"
            Image.fromarray(np.zeros((2, 2, 3), dtype=np.uint8), mode="RGB").save(webp, format="WEBP", lossless=True)
            sidecar.write_text(json.dumps({
                "encoding_version": 1,
                "decode": {"vmin": -100, "vmax": 100},
                "grid": {"width": 3, "height": 2}
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                decode_texture(webp, sidecar)


if __name__ == "__main__":
    unittest.main()
