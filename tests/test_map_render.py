import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from ecmwf_collector.tools.map_render import normalize_regular_grid, render_scalar_png, render_direction_png


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


    def test_reprojects_curvilinear_geolocation_grid(self):
        values = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype=np.float32)
        lat = np.array([[12, 12.1, 12.2], [11, 11.1, 11.2], [10, 10.1, 10.2]])
        lon = np.array([[30, 31, 32], [30.1, 31.1, 32.1], [30.2, 31.2, 32.2]])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "curvilinear.png"
            metadata = render_scalar_png(values, lat, lon, path)
            self.assertTrue(path.exists())
            self.assertEqual(metadata["source_grid_type"], "curvilinear_geolocation")
            self.assertEqual(metadata["render_projection"], "EPSG:3857")
            self.assertGreater(metadata["bounds"]["east"], metadata["bounds"]["west"])
            with Image.open(path) as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.size, (3, 3))

    def test_reprojects_curvilinear_grid_with_missing_geolocation_cells(self):
        values = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype=np.float32)
        lat = np.array([[12, 12.1, np.nan], [11, 11.1, 11.2], [10, 10.1, 10.2]])
        lon = np.array([[30, 31, np.nan], [30.1, 31.1, 32.1], [30.2, 31.2, 32.2]])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "curvilinear-masked.png"
            metadata = render_scalar_png(values, lat, lon, path)
            self.assertTrue(path.exists())
            self.assertGreater(metadata["valid_cells"], 0)
            self.assertEqual(metadata["source_grid_type"], "curvilinear_geolocation")

    def test_rejects_curvilinear_grid_with_insufficient_valid_points(self):
        values = np.array([[1, np.nan], [np.nan, np.nan]], dtype=np.float32)
        lat = np.array([[10, 10], [9, 9]], dtype=float)
        lon = np.array([[20, 21], [20, 21]], dtype=float)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "three valid geolocated"):
                render_scalar_png(values, lat, lon, Path(tmp) / "invalid.png")


    def test_direction_renderer_uses_cyclic_hue_and_transparent_missing_cells(self):
        directions = np.array([[359.0, 1.0], [90.0, np.nan]], dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "direction.png"
            metadata = render_direction_png(directions, [10, 0], [20, 21], path)
            self.assertEqual(metadata["value_min"], 0.0)
            self.assertEqual(metadata["value_max"], 360.0)
            self.assertEqual(metadata["resampling"], "circular_sine_cosine")
            with Image.open(path) as image:
                rgba = np.asarray(image)
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(rgba.shape[:2], (2, 2))
                self.assertEqual(int((rgba[..., 3] == 0).sum()), 1)

    def test_direction_renderer_supports_antimeridian_regular_grid(self):
        directions = np.array([[359, 1, 2], [358, 0, 3]], dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            result = render_direction_png(directions, [10, 0], [178, 180, 182],
                                          Path(tmp) / "direction-dateline.png")
            self.assertLess(result["bounds"]["west"], result["bounds"]["east"])
            self.assertEqual(result["longitude_convention"], "continuous_unwrapped")

    def test_direction_renderer_reprojects_curvilinear_grid(self):
        lat = np.array([[12, 12.1, 12.2], [11, 11.1, 11.2], [10, 10.1, 10.2]])
        lon = np.array([[30, 31, 32], [30.1, 31.1, 32.1], [30.2, 31.2, 32.2]])
        direction = np.array([[359, 1, 359], [359, 1, 359], [359, 1, 359]], dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            result = render_direction_png(direction, lat, lon, Path(tmp) / "curvilinear-direction.png")
            self.assertEqual(result["longitude_convention"], "curvilinear_unwrapped")
            self.assertEqual(result["resampling"], "circular_sine_cosine")
            self.assertGreater(result["valid_cells"], 0)

    def test_direction_renderer_rejects_all_missing_bearings(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "no valid bearings"):
                render_direction_png(np.full((2, 2), np.nan), [10, 0], [20, 21],
                                     Path(tmp) / "empty-direction.png")


    def test_opposing_interpolated_bearings_are_marked_ambiguous(self):
        lat = np.array([[12, 12.1, 12.2], [11, 11.1, 11.2], [10, 10.1, 10.2]])
        lon = np.array([[30, 31, 32], [30.1, 31.1, 32.1], [30.2, 31.2, 32.2]])
        direction = np.array([[0, 0, 180], [0, 0, 180], [0, 0, 180]], dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ambiguous.png"
            result = render_direction_png(direction, lat, lon, path)
            with Image.open(path) as image:
                alpha = np.asarray(image)[..., 3]
            self.assertGreater(result["missing_cells"], 0)
            self.assertGreater(int((alpha == 0).sum()), 0)


    def test_rejects_global_curvilinear_scalar_grid_until_seam_aware_rendering(self):
        lat = np.tile(np.array([20.0, 10.0, 0.0])[:, None], (1, 4))
        lon = np.tile(np.array([0.0, 90.0, 180.0, 270.0])[None, :], (3, 1))
        values = np.arange(12, dtype=np.float32).reshape(3, 4)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "seam-aware global rendering"):
                render_scalar_png(values, lat, lon, Path(tmp) / "global-curvilinear.png")

    def test_rejects_global_curvilinear_direction_grid_until_seam_aware_rendering(self):
        lat = np.tile(np.array([20.0, 10.0, 0.0])[:, None], (1, 4))
        lon = np.tile(np.array([0.0, 90.0, 180.0, 270.0])[None, :], (3, 1))
        direction = np.full((3, 4), 225.0, dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "seam-aware global rendering"):
                render_direction_png(direction, lat, lon, Path(tmp) / "global-direction.png")



    def test_reprojects_regional_curvilinear_grid_across_antimeridian(self):
        lat = np.array([[12.0, 12.0, 12.0], [10.0, 10.0, 10.0], [8.0, 8.0, 8.0]])
        lon = np.array([[179.0, -180.0, -179.0],
                        [179.2, -179.8, -178.8],
                        [179.4, -179.6, -178.6]])
        values = np.arange(9, dtype=np.float32).reshape(3, 3)
        with tempfile.TemporaryDirectory() as tmp:
            result = render_scalar_png(values, lat, lon, Path(tmp) / "regional-dateline.png")
        self.assertLess(result["bounds"]["east"] - result["bounds"]["west"], 5.0)
        self.assertGreater(result["bounds"]["east"], 180.0)
        self.assertEqual(result["longitude_convention"], "curvilinear_unwrapped")

    def test_reprojects_curvilinear_direction_across_antimeridian_cyclically(self):
        lat = np.array([[12.0, 12.0, 12.0], [10.0, 10.0, 10.0], [8.0, 8.0, 8.0]])
        lon = np.array([[179.0, -180.0, -179.0],
                        [179.2, -179.8, -178.8],
                        [179.4, -179.6, -178.6]])
        direction = np.array([[359.0, 0.0, 1.0], [359.0, 0.0, 1.0],
                              [359.0, 0.0, 1.0]], dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            result = render_direction_png(direction, lat, lon, Path(tmp) / "regional-direction-dateline.png")
        self.assertLess(result["bounds"]["east"] - result["bounds"]["west"], 5.0)
        self.assertGreater(result["valid_cells"], 0)
        self.assertEqual(result["longitude_convention"], "curvilinear_unwrapped")



if __name__ == "__main__":
    unittest.main()
