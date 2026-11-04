import unittest

import numpy as np

from ecmwf_collector.tools.wind_grib_to_webp import (
    spatial_layout,
    wind_speed_and_direction,
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

    def test_speed_and_meteorological_direction_from(self):
        u = np.array([[0.0, 10.0, 0.0, -10.0, 0.0]], dtype=np.float32)
        v = np.array([[-10.0, 0.0, 10.0, 0.0, 0.0]], dtype=np.float32)
        speed, direction = wind_speed_and_direction(u, v)
        np.testing.assert_allclose(speed[0, :4], [10, 10, 10, 10])
        np.testing.assert_allclose(direction[0, :4], [0, 270, 180, 90])
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
