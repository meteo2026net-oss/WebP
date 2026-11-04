import unittest

import numpy as np

from ecmwf_collector.tools.meteorological_units import (
    canonical_unit,
    convert_values,
)


class MeteorologicalUnitTests(unittest.TestCase):
    def test_pressure_conversions(self):
        self.assertAlmostEqual(convert_values(101325, "Pa", "hPa"), 1013.25)
        self.assertAlmostEqual(convert_values(1000, "hPa", "kPa"), 100.0)

    def test_temperature_conversions(self):
        self.assertAlmostEqual(convert_values(273.15, "K", "degC"), 0.0)
        self.assertAlmostEqual(convert_values(20, "°C", "K"), 293.15)

    def test_wind_speed_conversions(self):
        self.assertAlmostEqual(convert_values(10, "m/s", "km/h"), 36.0)
        self.assertAlmostEqual(convert_values(1, "m s-1", "knots"), 1.9438444924, places=7)

    def test_precipitation_depth_conversions(self):
        self.assertAlmostEqual(convert_values(12.5, "mm", "m"), 0.0125)
        self.assertAlmostEqual(convert_values(0.02, "m", "mm"), 20.0)

    def test_array_conversion_preserves_nan(self):
        result = convert_values(np.array([0.0, 10.0, np.nan]), "m/s", "km/h")
        np.testing.assert_allclose(result[:2], [0.0, 36.0])
        self.assertTrue(np.isnan(result[2]))

    def test_common_grib_pressure_aliases(self):
        for alias in ("hPa", "hectopascal", "hectopascals", "mbar", "millibar", "millibars"):
            with self.subTest(alias=alias):
                self.assertAlmostEqual(convert_values(1013.25, alias, "Pa"), 101325.0)

    def test_common_cfgrib_temperature_aliases(self):
        for alias in ("degC", "degree Celsius", "degrees Celsius", "deg C", "°C"):
            with self.subTest(alias=alias):
                self.assertAlmostEqual(convert_values(0, alias, "K"), 273.15)

    def test_common_cfgrib_wind_speed_aliases(self):
        for alias in ("m s-1", "m s**-1", "m s^-1", "m s**(-1)", "m/s"):
            with self.subTest(alias=alias):
                self.assertAlmostEqual(convert_values(10, alias, "km/h"), 36.0)
        for alias in ("km h-1", "km h**-1", "km h^-1", "km/h"):
            with self.subTest(alias=alias):
                self.assertAlmostEqual(convert_values(36, alias, "m/s"), 10.0)

    def test_unit_aliases_normalize_unicode_minus_and_middle_dot(self):
        self.assertAlmostEqual(convert_values(10, "m · s−1", "km/h"), 36.0)

    def test_precipitation_rates_are_a_separate_dimension(self):
        self.assertAlmostEqual(convert_values(1, "mm h-1", "mm s-1"), 1 / 3600)
        self.assertAlmostEqual(convert_values(24, "mm day-1", "mm h-1"), 1.0)
        self.assertAlmostEqual(convert_values(2, "mm/s", "mm h-1"), 7200.0)
        with self.assertRaisesRegex(ValueError, "Incompatible"):
            convert_values(1, "mm h-1", "mm")

    def test_mass_flux_is_not_assumed_to_be_depth_rate(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            convert_values(1, "kg m-2 s-1", "mm h-1")

    def test_equivalent_unit_aliases_have_same_canonical_label(self):
        self.assertEqual(canonical_unit("m/s"), canonical_unit("m s-1"))
        self.assertEqual(canonical_unit("mbar"), canonical_unit("hPa"))

    def test_unknown_and_incompatible_units_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            convert_values(1, "furlong", "m")
        with self.assertRaisesRegex(ValueError, "Incompatible"):
            convert_values(1, "hPa", "km/h")

    def test_missing_unit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-empty"):
            convert_values(1, "", "Pa")


if __name__ == "__main__":
    unittest.main()
