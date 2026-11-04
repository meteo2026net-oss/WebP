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


if __name__ == "__main__":
    unittest.main()
