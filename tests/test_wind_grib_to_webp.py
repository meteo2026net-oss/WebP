import unittest
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import xarray as xr

import numpy as np

from ecmwf_collector.tools.wind_grib_to_webp import (
    spatial_layout,
    validate_component_geolocation,
    wind_speed_and_direction,
    compatible_component_units,
    optional_bool,
    rotate_grid_to_earth,
    main,
)


class FakeCoordinate:
    def __init__(self, values, dims):
        self.values = np.asarray(values)
        self.dims = tuple(dims)
        self.ndim = self.values.ndim
        self.shape = self.values.shape


class FakeDataArray:
    def __init__(self, dims, coords):
        self.dims = tuple(dims)
        self.coords = coords

    def __getitem__(self, name):
        return self.coords[name]


class WindGridTests(unittest.TestCase):
    def test_regular_grid_layout(self):
        da = FakeDataArray(
            ("latitude", "longitude"),
            {
                "latitude": FakeCoordinate([10.0, 9.0], ("latitude",)),
                "longitude": FakeCoordinate([20.0, 21.0, 22.0], ("longitude",)),
            },
        )
        row, col, lat, lon, grid_type = spatial_layout(da)
        self.assertEqual((row, col), ("latitude", "longitude"))
        self.assertEqual(grid_type, "regular_latitude_longitude")
        np.testing.assert_array_equal(lat, [10.0, 9.0])
        np.testing.assert_array_equal(lon, [20.0, 21.0, 22.0])

    def test_curvilinear_grid_layout(self):
        lat = np.array([[10.0, 10.1], [9.0, 9.1]])
        lon = np.array([[20.0, 21.0], [20.1, 21.1]])
        da = FakeDataArray(
            ("y", "x"),
            {
                "latitude": FakeCoordinate(lat, ("y", "x")),
                "longitude": FakeCoordinate(lon, ("y", "x")),
            },
        )
        row, col, out_lat, out_lon, grid_type = spatial_layout(da)
        self.assertEqual((row, col), ("y", "x"))
        self.assertEqual(grid_type, "curvilinear_geolocation")
        np.testing.assert_array_equal(out_lat, lat)
        np.testing.assert_array_equal(out_lon, lon)

    def test_rejects_regular_wind_longitude_outside_angular_range(self):
        da = FakeDataArray(
            ("latitude", "longitude"),
            {
                "latitude": FakeCoordinate([10.0, 9.0], ("latitude",)),
                "longitude": FakeCoordinate([20.0, 361.0], ("longitude",)),
            },
        )
        with self.assertRaisesRegex(ValueError, "-360..360"):
            spatial_layout(da)

    def test_rejects_extreme_finite_curvilinear_wind_longitude(self):
        da = FakeDataArray(
            ("y", "x"),
            {
                "latitude": FakeCoordinate([[10.0, 10.0], [9.0, 9.0]], ("y", "x")),
                "longitude": FakeCoordinate([[20.0, 1e308], [21.0, 22.0]], ("y", "x")),
            },
        )
        with self.assertRaisesRegex(ValueError, "-360..360"):
            spatial_layout(da)

    def test_rejects_mismatched_curvilinear_geolocation_validity_masks(self):
        da = FakeDataArray(
            ("y", "x"),
            {
                "latitude": FakeCoordinate([[10.0, np.nan], [9.0, 9.0]], ("y", "x")),
                "longitude": FakeCoordinate([[20.0, 21.0], [21.0, 22.0]], ("y", "x")),
            },
        )
        with self.assertRaisesRegex(ValueError, "validity masks differ"):
            spatial_layout(da)

    def test_rejects_mismatched_geolocation_shapes(self):
        da = FakeDataArray(
            ("y", "x"),
            {
                "latitude": FakeCoordinate(np.ones((2, 2)), ("y", "x")),
                "longitude": FakeCoordinate(np.ones((2, 3)), ("y", "x")),
            },
        )
        with self.assertRaisesRegex(ValueError, "matching 2-D"):
            spatial_layout(da)

    def test_component_geolocation_requires_identical_curvilinear_coordinates(self):
        coords_u = {
            "latitude": (("y", "x"), [[10.0, 10.0], [9.0, 9.0]]),
            "longitude": (("y", "x"), [[20.0, 21.0], [20.0, 21.0]]),
        }
        coords_v = {
            "latitude": (("y", "x"), [[10.0, 10.0], [9.0, 9.0]]),
            "longitude": (("y", "x"), [[20.1, 21.1], [20.1, 21.1]]),
        }
        u_da = xr.DataArray(np.ones((2, 2)), dims=("y", "x"), coords=coords_u)
        v_da = xr.DataArray(np.ones((2, 2)), dims=("y", "x"), coords=coords_v)
        with self.assertRaisesRegex(ValueError, "different longitude coordinates"):
            validate_component_geolocation(u_da, v_da)

    def test_component_geolocation_accepts_matching_curvilinear_coordinates(self):
        coords = {
            "latitude": (("y", "x"), [[10.0, 10.0], [9.0, 9.0]]),
            "longitude": (("y", "x"), [[20.0, 21.0], [20.0, 21.0]]),
        }
        u_da = xr.DataArray(np.ones((2, 2)), dims=("y", "x"), coords=coords)
        v_da = xr.DataArray(np.ones((2, 2)), dims=("y", "x"), coords=coords)
        layout = validate_component_geolocation(u_da, v_da)
        self.assertEqual(layout[4], "curvilinear_geolocation")

    def test_speed_and_meteorological_direction_from(self):
        u = np.array([[0.0, 10.0, 0.0, -10.0, 0.0]], dtype=np.float32)
        v = np.array([[-10.0, 0.0, 10.0, 0.0, 0.0]], dtype=np.float32)
        speed, direction = wind_speed_and_direction(u, v)
        np.testing.assert_allclose(speed[0, :4], [10, 10, 10, 10])
        np.testing.assert_allclose(direction[0, :4], [0, 270, 180, 90])
        self.assertTrue(np.isnan(direction[0, 4]))

    def test_grid_rotation_cardinal_vectors(self):
        east, north = rotate_grid_to_earth(np.array([1.0, 0.0]), np.array([0.0, 1.0]), 90.0)
        np.testing.assert_allclose(east, [0.0, -1.0], atol=1e-7)
        np.testing.assert_allclose(north, [1.0, 0.0], atol=1e-7)

    def test_grid_rotation_preserves_wind_speed(self):
        u = np.array([[3.0, 0.0]], dtype=np.float32)
        v = np.array([[4.0, 2.0]], dtype=np.float32)
        east, north = rotate_grid_to_earth(u, v, 37.0)
        np.testing.assert_allclose(np.hypot(east, north), np.hypot(u, v), atol=1e-6)

    def test_grid_rotation_rejects_invalid_inputs(self):
        with self.assertRaisesRegex(ValueError, "identical shapes"):
            rotate_grid_to_earth(np.zeros((2, 2)), np.zeros((2, 3)), 0.0)
        with self.assertRaisesRegex(ValueError, "finite"):
            rotate_grid_to_earth(np.zeros(2), np.zeros(2), np.nan)
    def test_missing_component_produces_missing_speed_and_direction(self):
        u = np.array([[np.nan, 1.0]], dtype=np.float32)
        v = np.array([[1.0, np.nan]], dtype=np.float32)
        speed, direction = wind_speed_and_direction(u, v)
        self.assertTrue(np.all(np.isnan(speed)))
        self.assertTrue(np.all(np.isnan(direction)))

    def test_optional_bool_parses_ec_codes_values_without_truthiness_traps(self):
        self.assertIs(optional_bool(True), True)
        self.assertIs(optional_bool(1), True)
        self.assertIs(optional_bool("1"), True)
        self.assertIs(optional_bool("true"), True)
        self.assertIs(optional_bool(False), False)
        self.assertIs(optional_bool(0), False)
        self.assertIs(optional_bool("0"), False)
        self.assertIs(optional_bool("false"), False)
        self.assertIsNone(optional_bool(None))
        self.assertIsNone(optional_bool("unknown"))

    def test_component_units_must_match(self):
        self.assertEqual(compatible_component_units("m s-1", "m s-1"), "m s-1")
        self.assertEqual(compatible_component_units("m/s", "m s-1"), "m/s")
        self.assertEqual(compatible_component_units(None, "m/s"), "m/s")
        self.assertIsNone(compatible_component_units(None, None))
        with self.assertRaisesRegex(ValueError, "units differ"):
            compatible_component_units("m s-1", "knots")

    def test_rejects_different_component_shapes(self):
        with self.assertRaisesRegex(ValueError, "identical shapes"):
            wind_speed_and_direction(np.zeros((2, 2)), np.zeros((2, 3)))


    def _run_wind_cli(self, root, frame_flag, angle=None):
        lat = [10.0, 9.0]
        lon = [20.0, 21.0]
        coords = {"latitude": lat, "longitude": lon}
        attrs = {"units": "m s-1"}
        if frame_flag is not None:
            attrs["GRIB_uvRelativeToGrid"] = frame_flag
        dataset = xr.Dataset({
            "u10": xr.DataArray([[1.0, 2.0], [3.0, 4.0]],
                                dims=("latitude", "longitude"), coords=coords,
                                attrs=dict(attrs)),
            "v10": xr.DataArray([[2.0, 1.0], [4.0, 3.0]],
                                dims=("latitude", "longitude"), coords=coords,
                                attrs=dict(attrs)),
        })
        output = Path(root) / "wind.webp"
        argv = ["wind_grib_to_webp.py", str(Path(root) / "wind.grib2"),
                "--output", str(output)]
        if angle is not None:
            argv.extend(["--grid-to-earth-angle-deg", str(angle)])
        (Path(root) / "wind.grib2").touch()
        previous = os.getcwd()
        try:
            os.chdir(root)
            with (
                patch.object(sys, "argv", argv),
                patch("xarray.open_dataset", return_value=dataset),
                patch("ecmwf_collector.tools.wind_grib_to_webp.render_wind_speed_png",
                      return_value={"bounds": {"west": 20, "east": 21, "south": 9, "north": 10}}),
                patch("ecmwf_collector.tools.wind_grib_to_webp.render_direction_png",
                      return_value={"bounds": {"west": 20, "east": 21, "south": 9, "north": 10}}),
            ):
                main()
        finally:
            os.chdir(previous)
        return json.loads(output.with_suffix(".json").read_text(encoding="utf-8")), Path(root) / "output" / "map_data"

    def test_wind_manifest_source_id_is_content_derived(self):
        with tempfile.TemporaryDirectory() as root:
            metadata, map_dir = self._run_wind_cli(root, "0")
            manifest = json.loads((map_dir / "manifest.json").read_text(encoding="utf-8"))
            source_ids = {item["source_id"] for item in manifest["layers"]}
            self.assertEqual(len(source_ids), 1)
            expected = __import__(
                "ecmwf_collector.tools.grib_to_map", fromlist=["_source_id"]
            )._source_id(Path(root) / "wind.grib2")
            self.assertEqual(source_ids, {expected})

    def test_grid_relative_wind_does_not_publish_true_north_direction_layer(self):
        with tempfile.TemporaryDirectory() as root:
            metadata, map_dir = self._run_wind_cli(root, "1")
            self.assertEqual(metadata["component_frame"], "grid_relative")
            self.assertFalse(metadata["wind_direction"]["valid_for_earth_bearing"])
            self.assertFalse(metadata["direction_display_layer"]["published"])
            manifest = json.loads((map_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual([item["variable"] for item in manifest["layers"]], ["wind_speed"])

    def test_unknown_wind_reference_frame_does_not_publish_direction_layer(self):
        with tempfile.TemporaryDirectory() as root:
            metadata, map_dir = self._run_wind_cli(root, None)
            self.assertEqual(metadata["component_frame"], "unknown")
            self.assertIsNone(metadata["wind_direction"]["valid_for_earth_bearing"])
            self.assertFalse(metadata["direction_display_layer"]["published"])
            manifest = json.loads((map_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual([item["variable"] for item in manifest["layers"]], ["wind_speed"])

    def test_earth_relative_wind_publishes_true_north_direction_layer(self):
        with tempfile.TemporaryDirectory() as root:
            metadata, map_dir = self._run_wind_cli(root, "0")
            self.assertEqual(metadata["component_frame"], "earth_relative")
            self.assertTrue(metadata["wind_direction"]["valid_for_earth_bearing"])
            self.assertEqual(metadata["direction_display_layer"]["bearing_validity"],
                             "valid_true_north_bearing")
            manifest = json.loads((map_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {item["variable"] for item in manifest["layers"]},
                {"wind_speed", "wind_direction"},
            )

    def test_explicit_rotation_enables_direction_only_for_grid_relative_components(self):
        with tempfile.TemporaryDirectory() as root:
            metadata, map_dir = self._run_wind_cli(root, "1", angle=90)
            self.assertEqual(metadata["component_frame"], "grid_relative")
            self.assertEqual(metadata["direction_component_frame"], "earth_relative")
            self.assertTrue(metadata["grid_to_earth_rotation"]["applied"])
            self.assertTrue(metadata["wind_direction"]["valid_for_earth_bearing"])
            manifest = json.loads((map_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {item["variable"] for item in manifest["layers"]},
                {"wind_speed", "wind_direction"},
            )

    def test_rotation_argument_is_rejected_for_unknown_or_earth_relative_components(self):
        for frame in (None, "0"):
            with self.subTest(frame=frame), tempfile.TemporaryDirectory() as root:
                lat, lon = [10.0, 9.0], [20.0, 21.0]
                coords = {"latitude": lat, "longitude": lon}
                attrs = {"units": "m s-1"}
                if frame is not None:
                    attrs["GRIB_uvRelativeToGrid"] = frame
                dataset = xr.Dataset({
                    "u10": xr.DataArray(np.ones((2, 2)), dims=("latitude", "longitude"),
                                        coords=coords, attrs=dict(attrs)),
                    "v10": xr.DataArray(np.ones((2, 2)), dims=("latitude", "longitude"),
                                        coords=coords, attrs=dict(attrs)),
                })
                previous = os.getcwd()
                try:
                    os.chdir(root)
                    source = Path(root) / "wind.grib2"
                    source.touch()
                    with (patch.object(sys, "argv", ["wind.py", str(source), "--output",
                                                      str(Path(root) / "wind.webp"),
                                                      "--grid-to-earth-angle-deg", "45"]),
                          patch("xarray.open_dataset", return_value=dataset)):
                        with self.assertRaisesRegex(ValueError, "explicitly marking U/V as grid-relative"):
                            main()
                finally:
                    os.chdir(previous)



if __name__ == "__main__":
    unittest.main()
