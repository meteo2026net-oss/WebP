import unittest
import numpy as np
from ecmwf_collector.tools.circular_angles import circular_mean_degrees, interpolate_direction_degrees

class CircularDirectionTests(unittest.TestCase):
    def test_wraps_across_north(self):
        result = interpolate_direction_degrees([359.0, 1.0], [0.5, 0.5])
        self.assertTrue(min(abs(result), abs(result - 360.0)) < 1e-8)
    def test_cardinal_directions(self):
        self.assertAlmostEqual(float(circular_mean_degrees([0.0, 0.0])), 0.0)
        self.assertAlmostEqual(float(circular_mean_degrees([180.0, 180.0])), 180.0)
    def test_opposite_directions_are_undefined(self):
        self.assertTrue(np.isnan(circular_mean_degrees([90.0, 270.0])))
    def test_missing_values_are_ignored(self):
        result = interpolate_direction_degrees([np.nan, 359.0, 1.0], [1.0, 0.5, 0.5])
        self.assertTrue(min(abs(result), abs(result - 360.0)) < 1e-8)
        self.assertTrue(np.isnan(circular_mean_degrees([np.nan, np.nan])))
    def test_weighted_result(self):
        result = interpolate_direction_degrees([0.0, 90.0], [3.0, 1.0])
        self.assertAlmostEqual(float(result), np.rad2deg(np.arctan2(1.0, 3.0)))
    def test_negative_weights_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-negative"):
            circular_mean_degrees([0.0, 90.0], [1.0, -1.0])

if __name__ == "__main__":
    unittest.main()
