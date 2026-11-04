import tempfile
import unittest
from pathlib import Path

import numpy as np

from ecmwf_collector.tools.point_query import sample_npz


class PointQueryTests(unittest.TestCase):
    def test_samples_nearest_cell_across_longitude_conventions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "field.npz"
            np.savez_compressed(
                path,
                values=np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
                latitudes=np.array([10.0, 0.0]),
                longitudes=np.array([179.0, -179.0]),
            )
            result = sample_npz(path, 9.8, 180.0)
            self.assertTrue(result["valid"])
            self.assertEqual(result["value"], 1.0)
            self.assertEqual(result["latitude"], 10.0)

    def test_reports_missing_nearest_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "field.npz"
            np.savez_compressed(
                path,
                values=np.array([[np.nan, 2.0]], dtype=np.float32),
                latitudes=np.array([10.0]),
                longitudes=np.array([20.0, 21.0]),
            )
            result = sample_npz(path, 10.0, 20.0)
            self.assertFalse(result["valid"])
            self.assertIsNone(result["value"])

    def test_rejects_click_outside_grid_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "field.npz"
            np.savez_compressed(
                path,
                values=np.ones((2, 2), dtype=np.float32),
                latitudes=np.array([10.0, 9.0]),
                longitudes=np.array([20.0, 21.0]),
            )
            with self.assertRaisesRegex(ValueError, "outside the data grid"):
                sample_npz(path, 30.0, 40.0)

    def test_rejects_invalid_latitude(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "field.npz"
            np.savez_compressed(
                path,
                values=np.ones((2, 2), dtype=np.float32),
                latitudes=np.array([10.0, 0.0]),
                longitudes=np.array([20.0, 21.0]),
            )
            with self.assertRaises(ValueError):
                sample_npz(path, 95.0, 20.0)


if __name__ == "__main__":
    unittest.main()
