"""Integration tests for display-only unit conversion in the GRIB map pipeline."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import xarray as xr

from ecmwf_collector.tools.grib_to_map import convert_file


class GribMapDisplayUnitTests(unittest.TestCase):
    def _dataset(self, units="mm h-1"):
        field = xr.DataArray(
            [[1.0, np.nan], [2.0, 3.0]],
            dims=("latitude", "longitude"),
            coords={
                "latitude": [10.0, 20.0],
                "longitude": [30.0, 40.0],
            },
            attrs={"units": units, "long_name": "Precipitation rate"},
            name="prate",
        )
        return xr.Dataset({"prate": field})

    def _run(self, dataset, output_dir, display_unit="mm day-1"):
        fake_cfgrib = types.SimpleNamespace(
            open_datasets=lambda *args, **kwargs: [dataset]
        )
        with (
            patch.dict(sys.modules, {"cfgrib": fake_cfgrib}),
            patch(
                "ecmwf_collector.tools.grib_to_map.render_scalar_png",
                return_value={"width": 2, "height": 2},
            ),
            patch(
                "ecmwf_collector.tools.grib_to_map.update_manifest",
                return_value=output_dir / "manifest.json",
            ),
        ):
            source = output_dir / "synthetic.grib2"
            source.touch()
            return convert_file(source, output_dir, "prate", display_unit)

    def test_precipitation_rate_display_conversion_keeps_source_values(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            products = self._run(self._dataset(), output_dir)
            self.assertEqual(len(products), 1)
            metadata = products[0]
            self.assertEqual(metadata["source_units"], "mm h-1")
            self.assertEqual(metadata["display_units"], "mm day-1")
            self.assertTrue(metadata["display_conversion_applied"])
            with np.load(output_dir / metadata["data_file"]) as stored:
                np.testing.assert_allclose(
                    stored["values"][[0, 1], [0, 0]], [1.0, 2.0]
                )
                np.testing.assert_allclose(
                    stored["display_values"][[0, 1], [0, 0]], [24.0, 48.0]
                )
                self.assertTrue(np.isnan(stored["values"][0, 1]))
                self.assertTrue(np.isnan(stored["display_values"][0, 1]))

    def test_missing_source_unit_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            dataset = self._dataset()
            dataset["prate"].attrs.pop("units")
            with self.assertRaisesRegex(ValueError, "source unit metadata is missing"):
                self._run(dataset, output_dir)


    def test_pressure_temperature_and_wind_display_conversions_reach_renderer(self):
        cases = [
            ("Pa", "hPa", [[100000.0, 101325.0], [99000.0, 98000.0]], [[1000.0, 1013.25], [990.0, 980.0]]),
            ("K", "degC", [[273.15, 293.15], [300.0, 250.0]], [[0.0, 20.0], [26.85, -23.15]]),
            ("m s-1", "km/h", [[1.0, 5.0], [10.0, 20.0]], [[3.6, 18.0], [36.0, 72.0]]),
        ]
        for source_unit, target_unit, source_values, expected_display in cases:
            with self.subTest(source_unit=source_unit, target_unit=target_unit):
                with tempfile.TemporaryDirectory() as directory:
                    output_dir = Path(directory)
                    dataset = self._dataset(source_unit)
                    dataset["prate"].values[:] = np.asarray(source_values)
                    rendered = []

                    def capture(values, latitudes, longitudes, path):
                        rendered.append(np.asarray(values).copy())
                        return {"width": 2, "height": 2}

                    fake_cfgrib = types.SimpleNamespace(
                        open_datasets=lambda *args, **kwargs: [dataset]
                    )
                    with (
                        patch.dict(sys.modules, {"cfgrib": fake_cfgrib}),
                        patch("ecmwf_collector.tools.grib_to_map.render_scalar_png", side_effect=capture),
                        patch(
                            "ecmwf_collector.tools.grib_to_map.update_manifest",
                            return_value=output_dir / "manifest.json",
                        ),
                    ):
                        source = output_dir / "synthetic.grib2"
                        source.touch()
                        products = convert_file(source, output_dir, "prate", target_unit)

                    self.assertEqual(len(products), 1)
                    np.testing.assert_allclose(rendered[0], expected_display, atol=1e-5)
                    metadata = products[0]
                    self.assertEqual(metadata["source_units"], source_unit)
                    self.assertEqual(metadata["display_units"], {"degC": "°C", "km/h": "km h-1"}.get(target_unit, target_unit))
                    with np.load(output_dir / metadata["data_file"]) as stored:
                        np.testing.assert_allclose(stored["values"], source_values)
                        np.testing.assert_allclose(stored["display_values"], expected_display, atol=1e-5)

    def test_incompatible_and_unknown_display_units_fail_closed(self):
        for source_unit, target_unit, expected_error in (
            ("mm h-1", "hPa", "Incompatible"),
            ("mm h-1", "furlong", "Unsupported"),
        ):
            with self.subTest(source_unit=source_unit, target_unit=target_unit):
                with tempfile.TemporaryDirectory() as directory:
                    output_dir = Path(directory)
                    dataset = self._dataset(source_unit)
                    fake_cfgrib = types.SimpleNamespace(
                        open_datasets=lambda *args, **kwargs: [dataset]
                    )
                    with (
                        patch.dict(sys.modules, {"cfgrib": fake_cfgrib}),
                        patch("ecmwf_collector.tools.grib_to_map.render_scalar_png") as renderer,
                        patch(
                            "ecmwf_collector.tools.grib_to_map.update_manifest",
                            return_value=output_dir / "manifest.json",
                        ),
                    ):
                        source = output_dir / "synthetic.grib2"
                        source.touch()
                        with self.assertRaisesRegex(ValueError, expected_error):
                            convert_file(source, output_dir, "prate", target_unit)
                        renderer.assert_not_called()


    def test_splits_forecast_times_and_pressure_levels_into_independent_layers(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            times = np.array(["2026-11-04T00:00", "2026-11-04T06:00"], dtype="datetime64[ns]")
            field = xr.DataArray(
                np.arange(16, dtype=np.float32).reshape(2, 2, 2, 2),
                dims=("time", "isobaricInhPa", "latitude", "longitude"),
                coords={
                    "time": [0, 1],
                    "valid_time": ("time", times),
                    "step": ("time", np.array([0, 6], dtype="timedelta64[h]")),
                    "isobaricInhPa": [850, 500],
                    "latitude": [10.0, 20.0],
                    "longitude": [30.0, 40.0],
                },
                attrs={
                    "units": "K",
                    "long_name": "Air temperature",
                    "GRIB_typeOfLevel": "isobaricInhPa",
                },
                name="t",
            )
            dataset = xr.Dataset({"t": field})
            fake_cfgrib = types.SimpleNamespace(
                open_datasets=lambda *args, **kwargs: [dataset]
            )
            with (
                patch.dict(sys.modules, {"cfgrib": fake_cfgrib}),
                patch(
                    "ecmwf_collector.tools.grib_to_map.render_scalar_png",
                    return_value={"width": 2, "height": 2},
                ),
            ):
                source = output_dir / "multi-level-forecast.grib2"
                source.touch()
                products = convert_file(source, output_dir, "t")

            self.assertEqual(len(products), 4)
            self.assertEqual(
                {item["level"] for item in products},
                {850, 500},
            )
            self.assertEqual(
                {item["valid_time"] for item in products},
                {"2026-11-04T00:00:00.000000000", "2026-11-04T06:00:00.000000000"},
            )
            self.assertEqual({item["step"] for item in products}, {"0 seconds", "21600 seconds"})
            self.assertEqual(len({item["image"] for item in products}), 4)
            manifest = __import__("json").loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["layers"]), 4)
            for item in products:
                with np.load(output_dir / item["data_file"]) as stored:
                    self.assertEqual(stored["values"].shape, (2, 2))


if __name__ == "__main__":
    unittest.main()
