import tempfile
import unittest
from pathlib import Path

import numpy as np

from ecmwf_collector.tools.point_query import sample_npz


class PointQueryTests(unittest.TestCase):
    def _write_grid(self, root, values, latitudes, longitudes):
        path = Path(root) / "field.npz"
        np.savez_compressed(path, values=np.asarray(values, dtype=np.float32),
                            latitudes=np.asarray(latitudes, dtype=np.float64),
                            longitudes=np.asarray(longitudes, dtype=np.float64))
        return path

    def test_samples_nearest_cell_across_longitude_conventions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_grid(tmp, [[1, 2], [3, 4]], [10, 0], [179, -179])
            result = sample_npz(path, 9.8, 180.0)
            self.assertTrue(result["valid"])
            self.assertEqual(result["value"], 1.0)
            self.assertEqual(result["latitude"], 10.0)
            with self.assertRaisesRegex(ValueError, "outside the data grid"):
                sample_npz(path, 9.8, 170.0)

    def test_reports_missing_nearest_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_grid(tmp, [[np.nan, 2], [3, 4]], [10, 9], [20, 21])
            result = sample_npz(path, 10, 20)
            self.assertFalse(result["valid"])
            self.assertIsNone(result["value"])

    def test_rejects_click_outside_grid_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_grid(tmp, np.ones((2, 2)), [10, 9], [20, 21])
            with self.assertRaisesRegex(ValueError, "outside the data grid"):
                sample_npz(path, 30, 40)

    def test_rejects_non_monotonic_grid_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_grid(tmp, np.ones((2, 2)), [10, 10], [20, 21])
            with self.assertRaisesRegex(ValueError, "strictly monotonic"):
                sample_npz(path, 10, 20)

    def test_rejects_invalid_latitude(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_grid(tmp, np.ones((2, 2)), [10, 0], [20, 21])
            with self.assertRaises(ValueError):
                sample_npz(path, 95, 20)

    def test_bilinear_interpolates_exact_midpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_grid(tmp, [[0, 10], [20, 30]], [1, 0], [10, 11])
            result = sample_npz(path, 0.5, 10.5, method="bilinear")
            self.assertTrue(result["valid"])
            self.assertAlmostEqual(result["value"], 15.0)
            self.assertEqual(result["method"], "bilinear")

    def test_bilinear_handles_descending_axes_and_antimeridian(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_grid(tmp, [[0, 10], [20, 30]], [1, 0], [181, 180])
            result = sample_npz(path, 0.5, -179.5, method="bilinear")
            self.assertTrue(result["valid"])
            self.assertAlmostEqual(result["value"], 15.0)

    def test_bilinear_interpolates_across_global_longitude_seam(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = [[0, 90, 180, 270], [10, 100, 190, 280]]
            path = self._write_grid(tmp, values, [10, 0], [0, 90, 180, 270])
            result = sample_npz(path, 5.0, 315.0, method="bilinear")
            self.assertTrue(result["valid"])
            self.assertAlmostEqual(result["value"], 140.0)

    def test_nearest_sampling_drops_duplicate_global_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = [[1, 2, 3, 4, 99], [5, 6, 7, 8, 99]]
            path = self._write_grid(tmp, values, [10, 0], [0, 90, 180, 270, 360])
            result = sample_npz(path, 10.0, 0.0)
            self.assertTrue(result["valid"])
            self.assertEqual(result["value"], 1.0)

    def test_bilinear_rejects_global_axis_with_only_one_unique_longitude(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_grid(tmp, [[1, 1], [2, 2]], [10, 0], [0, 360])
            with self.assertRaisesRegex(ValueError, "at least two unique longitude columns"):
                sample_npz(path, 5.0, 180.0, method="bilinear")

    def test_bilinear_global_seam_drops_duplicate_cyclic_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = [[0, 90, 180, 270, 0], [10, 100, 190, 280, 10]]
            path = self._write_grid(tmp, values, [10, 0], [0, 90, 180, 270, 360])
            result = sample_npz(path, 5.0, -45.0, method="bilinear")
            self.assertTrue(result["valid"])
            self.assertAlmostEqual(result["value"], 140.0)

    def test_bilinear_refuses_missing_corner_instead_of_inventing_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_grid(tmp, [[0, np.nan], [20, 30]], [1, 0], [10, 11])
            result = sample_npz(path, 0.5, 10.5, method="bilinear")
            self.assertFalse(result["valid"])
            self.assertIsNone(result["value"])

    def test_bilinear_does_not_extrapolate_outside_grid_centres(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_grid(tmp, [[0, 10], [20, 30]], [1, 0], [10, 11])
            with self.assertRaisesRegex(ValueError, "outside the data grid"):
                sample_npz(path, 1.1, 10.5, method="bilinear")

    def test_rejects_unknown_sampling_method(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_grid(tmp, np.ones((2, 2)), [1, 0], [10, 11])
            with self.assertRaisesRegex(ValueError, "Sampling method"):
                sample_npz(path, 0.5, 10.5, method="cubic")

    def test_samples_nearest_cell_on_curvilinear_geolocation_grid(self):
        with tempfile.TemporaryDirectory() as tmp:
            lat = [[10.0, 10.1, 10.2], [9.0, 9.1, 9.2], [8.0, 8.1, 8.2]]
            lon = [[20.0, 21.0, 22.0], [20.1, 21.1, 22.1], [20.2, 21.2, 22.2]]
            values = np.arange(9, dtype=np.float32).reshape(3, 3)
            path = self._write_grid(tmp, values, lat, lon)
            result = sample_npz(path, 9.12, 21.12)
            self.assertTrue(result["valid"])
            self.assertEqual(result["value"], 4.0)
            self.assertEqual(result["grid_type"], "curvilinear")
            with self.assertRaisesRegex(ValueError, "outside the data grid"):
                sample_npz(path, 40.0, 80.0)

    def test_nearest_sampling_ignores_missing_curvilinear_geolocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            lat = [[10.0, 10.1, np.nan], [9.0, 9.1, 9.2], [8.0, 8.1, 8.2]]
            lon = [[20.0, 21.0, np.nan], [20.1, 21.1, 22.1], [20.2, 21.2, 22.2]]
            values = np.arange(9, dtype=np.float32).reshape(3, 3)
            path = self._write_grid(tmp, values, lat, lon)
            result = sample_npz(path, 9.12, 21.12)
            self.assertTrue(result["valid"])
            self.assertEqual(result["value"], 4.0)

    def test_curvilinear_nearest_rejects_isolated_cell_without_coverage_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            lat = np.array([
                [10.0, np.nan, 30.0],
                [np.nan, np.nan, np.nan],
                [np.nan, np.nan, 50.0],
            ])
            lon = np.array([
                [20.0, np.nan, 40.0],
                [np.nan, np.nan, np.nan],
                [np.nan, np.nan, 60.0],
            ])
            values = np.arange(9, dtype=np.float32).reshape(3, 3)
            path = self._write_grid(tmp, values, lat, lon)
            with self.assertRaisesRegex(ValueError, "coverage cannot be established"):
                sample_npz(path, 80.0, 100.0)

    def test_curvilinear_grid_rejects_bilinear_until_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            lat = [[10.0, 10.1], [9.0, 9.1]]
            lon = [[20.0, 21.0], [20.1, 21.1]]
            path = self._write_grid(tmp, [[1, 2], [3, 4]], lat, lon)
            with self.assertRaisesRegex(ValueError, "limited to regular 1-D"):
                sample_npz(path, 9.5, 20.5, method="bilinear")

    def test_curvilinear_nearest_sampling_crosses_antimeridian(self):
        with tempfile.TemporaryDirectory() as tmp:
            lat = [[10.0, 10.0, 10.0], [9.0, 9.0, 9.0], [8.0, 8.0, 8.0]]
            lon = [[179.8, -180.0, -179.8],
                   [179.8, -180.0, -179.8],
                   [179.8, -180.0, -179.8]]
            values = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype=np.float32)
            path = self._write_grid(tmp, values, lat, lon)
            east = sample_npz(path, 9.0, 179.85)
            west = sample_npz(path, 9.0, -179.85)
            across = sample_npz(path, 9.0, 180.15)
            self.assertEqual(east["value"], 4.0)
            self.assertEqual(west["value"], 6.0)
            self.assertEqual(across["value"], 6.0)
            self.assertEqual(west["longitude"], -179.8)
            self.assertEqual(west["grid_type"], "curvilinear")

    def test_curvilinear_nearest_sampling_rejects_far_side_of_dateline(self):
        with tempfile.TemporaryDirectory() as tmp:
            lat = [[10.0, 10.0, 10.0], [9.0, 9.0, 9.0], [8.0, 8.0, 8.0]]
            lon = [[179.8, -180.0, -179.8],
                   [179.8, -180.0, -179.8],
                   [179.8, -180.0, -179.8]]
            path = self._write_grid(tmp, np.arange(9).reshape(3, 3), lat, lon)
            with self.assertRaisesRegex(ValueError, "outside the data grid"):
                sample_npz(path, 9.0, 170.0)


    def test_curvilinear_nearest_sampling_supports_global_longitude_mesh(self):
        with tempfile.TemporaryDirectory() as tmp:
            lat = np.tile(np.array([60.0, 0.0, -60.0])[:, None], (1, 4))
            lon = np.tile(np.array([-180.0, -90.0, 0.0, 90.0])[None, :], (3, 1))
            values = np.arange(12, dtype=np.float32).reshape(3, 4)
            path = self._write_grid(tmp, values, lat, lon)
            result = sample_npz(path, 0.0, 179.0)
            self.assertTrue(result["valid"])
            self.assertEqual(result["value"], 4.0)
            self.assertEqual(result["longitude"], -180.0)
            self.assertEqual(result["grid_type"], "curvilinear")

    def test_curvilinear_nearest_uses_great_circle_distance_at_high_latitudes(self):
        with tempfile.TemporaryDirectory() as tmp:
            lat = [[88.0, 88.0, 88.0], [80.0, 80.0, 80.0], [72.0, 72.0, 72.0]]
            lon = [[-120.0, 0.0, 120.0], [-120.0, 0.0, 120.0], [-120.0, 0.0, 120.0]]
            values = np.arange(9, dtype=np.float32).reshape(3, 3)
            path = self._write_grid(tmp, values, lat, lon)
            result = sample_npz(path, 80.0, 160.0)
            self.assertTrue(result["valid"])
            self.assertEqual(result["value"], 5.0)
            self.assertEqual(result["longitude"], 120.0)


if __name__ == "__main__":
    unittest.main()
