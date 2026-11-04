import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from ecmwf_collector.tools.map_render import normalize_regular_grid, render_scalar_png


class MapRenderTests(unittest.TestCase):
    def test_normalizes_latitude_and_wrapped_longitude(self):
        values = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        lat = np.array([-10, 10])
        lon = np.array([0, 120, 240])
        data, out_lat, out_lon = normalize_regular_grid(values, lat, lon)
        self.assertEqual(out_lat.tolist(), [10, -10])
        self.assertTrue(np.all(np.diff(out_lon) > 0))
        self.assertEqual(data.shape, (2, 3))

    def test_rejects_irregular_longitude_grid(self):
        values = np.ones((2, 3), dtype=np.float32)
        with self.assertRaisesRegex(ValueError, "regularly spaced"):
            normalize_regular_grid(values, np.array([10, 0]), np.array([0, 1, 4]))

    def test_writes_transparent_georeferenced_png(self):
        values = np.array([[1, np.nan], [3, 4]], dtype=np.float32)
        lat = np.array([10, 0])
        lon = np.array([20, 21])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "field.png"
            metadata = render_scalar_png(values, lat, lon, path)
            self.assertTrue(path.exists())
            self.assertEqual(metadata["width"], 2)
            self.assertEqual(metadata["height"], 2)
            with Image.open(path) as image:
                self.assertEqual(image.mode, "RGBA")
                alpha = np.asarray(image)[..., 3]
                self.assertEqual(int((alpha == 0).sum()), 1)


if __name__ == "__main__":
    unittest.main()
