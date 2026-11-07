"""Tests for scientifically guarded model-to-model comparison."""
import unittest

import numpy as np

from ecmwf_collector.model_comparison import (
    ForecastField, ModelComparisonError, calculate_pair_metrics,
    compare_forecast_models,
)


def field(model, values, **overrides):
    metadata = dict(
        values=values, model=model, variable="t2m", level_type="heightAboveGround",
        level_value=2, level_unit="m", valid_time="2026-01-01T12:00:00Z",
        units="K", grid_id="regular-1",
    )
    metadata.update(overrides)
    return ForecastField(**metadata)


class ModelComparisonTests(unittest.TestCase):
    def test_metrics_and_temperature_conversion(self):
        result = calculate_pair_metrics(
            field("A", [[273.15, 274.15, np.nan]]),
            field("B", [[274.15, 276.15, 280.0]], units="degC"),
        )
        self.assertEqual(result["sample_count"], 2)
        self.assertAlmostEqual(result["bias"], 1.5)
        self.assertAlmostEqual(result["mae"], 1.5)
        self.assertAlmostEqual(result["rmse"], np.sqrt(2.5))
        self.assertEqual(result["error_sign"], "candidate_minus_reference")

    def test_pressure_conversion(self):
        result = calculate_pair_metrics(
            field("A", [100000.0], units="Pa", variable="msl"),
            field("B", [1000.0], units="hPa", variable="msl"),
        )
        self.assertAlmostEqual(result["bias"], 0.0)

    def test_precipitation_contingency_scores(self):
        result = calculate_pair_metrics(
            field("A", [0, 2, 0, 3], units="mm", variable="tp"),
            field("B", [0, 1, 4, 3], units="kg m-2", variable="tp"),
            precipitation_threshold=1.0,
        )["precipitation"]
        self.assertEqual((result["hits"], result["misses"], result["false_alarms"]), (2, 0, 1))
        self.assertAlmostEqual(result["pod"], 1.0)
        self.assertAlmostEqual(result["far"], 1 / 3)
        self.assertAlmostEqual(result["csi"], 2 / 3)

    def test_rejects_variable_time_level_grid_and_unknown_units(self):
        a = field("A", [1, 2])
        for changed in (
            field("B", [1, 2], variable="wind"),
            field("B", [1, 2], valid_time="2026-01-01T13:00:00Z"),
            field("B", [1, 2], level_value=10),
            field("B", [1, 2], grid_id="different-grid"),
            field("B", [1, 2], units="mystery"),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ModelComparisonError):
                    calculate_pair_metrics(a, changed)

    def test_rejects_incompatible_shape_and_no_overlap(self):
        with self.assertRaises(ModelComparisonError):
            calculate_pair_metrics(field("A", [1, 2]), field("B", [[1, 2]]))
        with self.assertRaises(ModelComparisonError):
            calculate_pair_metrics(field("A", [np.nan]), field("B", [2]))

    def test_precipitation_threshold_rejects_other_variables(self):
        with self.assertRaises(ModelComparisonError):
            calculate_pair_metrics(field("A", [1]), field("B", [2]),
                                   precipitation_threshold=1)

    def test_compare_collection_requires_explicit_reference(self):
        result = compare_forecast_models(
            {"A": field("A", [1, 2]), "B": field("B", [2, 4])},
            reference_model="A",
        )
        self.assertEqual(result["reference_model"], "A")
        self.assertAlmostEqual(result["comparisons"]["B"]["bias"], 1.5)


if __name__ == "__main__":
    unittest.main()
