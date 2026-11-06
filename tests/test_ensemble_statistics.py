"""Tests for safe gridpoint ensemble statistics."""
import unittest

import numpy as np

from ecmwf_collector.ensemble_statistics import (
    EnsembleStatisticsError, calculate_ensemble_statistics,
)


class EnsembleStatisticsTests(unittest.TestCase):
    def test_mean_population_spread_and_probability(self):
        result = calculate_ensemble_statistics(
            {"c00": [[1.0, 2.0]], "p01": [[3.0, 4.0]], "p02": [[5.0, 6.0]]},
            threshold=3.0,
        )
        np.testing.assert_allclose(result["mean"], [[3.0, 4.0]])
        np.testing.assert_allclose(result["spread"], [[np.sqrt(8 / 3), np.sqrt(8 / 3)]])
        np.testing.assert_allclose(
            result["probability_exceeding_threshold_percent"], [[66.6666667, 100.0]]
        )
        np.testing.assert_array_equal(result["member_count"], [[3, 3]])

    def test_missing_values_use_gridpoint_valid_member_denominator(self):
        result = calculate_ensemble_statistics(
            {"c00": [[1.0, np.nan]], "p01": [[3.0, 4.0]], "p02": [[np.nan, 8.0]]},
            threshold=2.0,
        )
        np.testing.assert_allclose(result["mean"], [[2.0, 6.0]])
        np.testing.assert_allclose(result["probability_exceeding_threshold_percent"], [[50, 100]])

    def test_cells_with_too_few_valid_members_are_nan(self):
        result = calculate_ensemble_statistics(
            {"c00": [[1.0, np.nan]], "p01": [[np.nan, 4.0]]},
            threshold=0.0,
        )
        self.assertTrue(np.isnan(result["mean"][0, 1]))
        self.assertTrue(np.isnan(result["spread"][0, 1]))
        self.assertTrue(np.isnan(result["probability_exceeding_threshold_percent"][0, 1]))

    def test_rejects_single_member_and_shape_mismatch(self):
        with self.assertRaises(EnsembleStatisticsError):
            calculate_ensemble_statistics({"c00": [1, 2]})
        with self.assertRaises(EnsembleStatisticsError):
            calculate_ensemble_statistics({"c00": [1, 2], "p01": [[1, 2]]})

    def test_rejects_non_numeric_fields_and_bad_minimum(self):
        with self.assertRaises(EnsembleStatisticsError):
            calculate_ensemble_statistics({"c00": [1], "p01": ["bad"]})
        with self.assertRaises(EnsembleStatisticsError):
            calculate_ensemble_statistics({"c00": [1], "p01": [2]}, minimum_members=1)


if __name__ == "__main__":
    unittest.main()
