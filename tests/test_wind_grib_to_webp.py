import unittest

import numpy as np
import xarray as xr

from ecmwf_collector.tools.wind_grib_to_webp import (
    spatial_layout,
    wind_speed_and_direction,
)


class WindGridTests(unittest.TestCase):
    def test_regular_grid_layout(self):
        da = xr.DataArray(
            np.zeros((2, 3), dtype=np.float32),
            dims=("latitude", "longitude"),
            coords={"latitude": [10.0, 9.0], "longitude": [20.0, 21.0, 22.0]},
        )
        row, col, lat, lon, grid_type = spatial_layout(da)
        self.assertEqual((row, col), ("latitude", "longitude"))
        self.assertEqual(grid_type, "regular_latitude_longitude")
        np.testing.assert_array_equal(lat, [10.0, 9.0])
        np.testing.assert_array_equal(lon, [20.0, 21.0, 22.0])

    def test_curvilinear_grid_layout(self):
        lat = np.array([[10.0, 10.1], [9.0, 9.1]])
        lon = np.array([[20.0, 21.0], [20.1, 21.1]])
        da = xr.DataArray(
            np.zeros((2, 2), dtype=np.float32),
            dims=("y", "x"),
            coords={
                "latitude": (("y", "x"), lat),
                "longitude": (("y", "x"), lon),
            },
        )
        row, col, out_lat, out_lon, grid_type = spatial_layout(da)
        self.assertEqual((row, col), ("y", "x"))
        self.assertEqual(grid_type, "curvilinear_geolocation")
        np.testing.assert_array_equal(out_lat, lat)
        np.testing.assert_array_equal(out_lon, lon)

    def test_rejects_mismatched_geolocation_shapes(self):
        da = xr.DataArray(
            np.zeros((2, 2), dtype=np.float32),
            dims=("y", "x"),
            coords={
                "latitude": (("y", "x"), np.ones((2, 2))),
                "longitude": (("y", "x"), np.ones((2, 3))),
            },
        )
        with self.assertRaisesRegex(ValueError, "matching 2-D"):
            spatial_layout(da)

    def test_speed_and_meteorological_direction_from(self):
        u = np.array([[0.0, 10.0, 0.0, -10.0, 0.0]], dtype=np.float32)
        v = np.array([[-10.0, 0.0, 10.0, 0.0, 0.0]], dtype=np.float32)
        speed, direction = wind_speed_and_direction(u, v)
        np.testing.assert_allclose(speed[0, :4], [10, 10, 10, 10])
        np.testing.assert_allclose(direction[0, :4], [180, 270, 0, 90])
        self.assertTrue(np.isnan(direction[0, 4]))

    def test_missing_component_produces_missing_speed_and_direction(self):
        u = np.array([[np.nan, 1.0]], dtype=np.float32)
        v = np.array([[1.0, np.nan]], dtype=np.float32)
        speed, direction = wind_speed_and_direction(u, v)
        self.assertTrue(np.all(np.isnan(speed)))
        self.assertTrue(np.all(np.isnan(direction)))

    def test_rejects_different_component_shapes(self):
        with self.assertRaisesRegex(ValueError, "identical shapes"):
            wind_speed_and_direction(np.zeros((2, 2)), np.zeros((2, 3)))


if __name__ == "__main__":
    unittest.main()
