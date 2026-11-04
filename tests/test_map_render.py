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
        data, out_lat, out_lon, _ = normalize_regular_grid(values, lat, lon)
        self.assertEqual(out_lat.tolist(), [10, -10])
        self.assertTrue(np.all(np.diff(out_lon) > 0))
        self.assertEqual(data.shape, (2, 3))

    def test_longitude_wrap_preserves_data_cell_alignment(self):
        values = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        lat = np.array([-10, 10])
        lon = np.array([0, 120, 240])
        data, out_lat, out_lon, _ = normalize_regular_grid(values, lat, lon)
        np.testing.assert_array_equal(out_lat, [10, -10])
        np.testing.assert_array_equal(out_lon, [-120, 0, 120])
        np.testing.assert_array_equal(data, [[6, 4, 5], [3, 1, 2]])

    def test_unwraps_grid_crossing_the_antimeridian_without_reordering_cells(self):
        values = np.array([[1, 2, 3, 4, 5], [6, 7, 8, 9, 10]], dtype=np.float32)
        lat = np.array([10, 0])
        lon = np.array([170, 175, 180, 185, 190])
        data, out_lat, out_lon, convention = normalize_regular_grid(values, lat, lon)
        np.testing.assert_array_equal(out_lat, [10, 0])
        np.testing.assert_array_equal(out_lon, [170, 175, 180, 185, 190])
        np.testing.assert_array_equal(data, values)
        self.assertEqual(convention, "continuous_unwrapped")

    def test_unwraps_descending_grid_crossing_the_antimeridian(self):
        values = np.array([[1, 2, 3, 4, 5], [6, 7, 8, 9, 10]], dtype=np.float32)
        lon = np.array([190, 185, 180, 175, 170])
        data, _, out_lon, convention = normalize_regular_grid(values, [10, 0], lon)
        np.testing.assert_array_equal(out_lon, [170, 175, 180, 185, 190])
        np.testing.assert_array_equal(data, values[:, ::-1])
        self.assertEqual(convention, "continuous_unwrapped")

    def test_render_bounds_extend_across_antimeridian(self):
        values = np.arange(10, dtype=np.float32).reshape(2, 5)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dateline.png"
            metadata = render_scalar_png(values, [10, 0], [170, 175, 180, 185, 190], path)
            self.assertLess(metadata["bounds"]["west"], 180)
            self.assertGreater(metadata["bounds"]["east"], 180)
            self.assertEqual(metadata["longitude_convention"], "continuous_unwrapped")
            self.assertTrue(path.exists())

    def test_global_grid_bounds_keep_the_full_world_width(self):
        values = np.arange(8, dtype=np.float32).reshape(2, 4)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "global.png"
            metadata = render_scalar_png(values, [10, 0], [0, 90, 180, 270], path)
            bounds = metadata["bounds"]
            self.assertAlmostEqual(bounds["east"] - bounds["west"], 360.0)
            self.assertEqual(metadata["width"], 4)

    def test_removes_duplicate_cyclic_longitude_endpoint(self):
        values = np.array([[1, 2, 3, 4, 99], [5, 6, 7, 8, 100]], dtype=np.float32)
        lat = np.array([10, 0])
        lon = np.array([0, 90, 180, 270, 360])
        data, _, out_lon, _ = normalize_regular_grid(values, lat, lon)
        self.assertEqual(out_lon.size, 4)
        self.assertEqual(data.shape, (2, 4))
        self.assertNotIn(99, data)
        self.assertNotIn(100, data)

    def test_rejects_duplicate_or_non_monotonic_latitudes(self):
        values = np.ones((3, 2), dtype=np.float32)
        with self.assertRaisesRegex(ValueError, "strictly monotonic"):
            normalize_regular_grid(values, np.array([0, 1, 0]), np.array([0, 1]))

    def test_rejects_latitude_outside_geographic_range(self):
        values = np.ones((2, 2), dtype=np.float32)
        with self.assertRaisesRegex(ValueError, "-90..90"):
            normalize_regular_grid(values, np.array([91, 90]), np.array([0, 1]))

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
            self.assertEqual(metadata["render_projection"], "EPSG:3857")
            with Image.open(path) as image:
                self.assertEqual(image.mode, "RGBA")
                alpha = np.asarray(image)[..., 3]
                self.assertEqual(int((alpha == 0).sum()), 1)


if __name__ == "__main__":
    unittest.main()
