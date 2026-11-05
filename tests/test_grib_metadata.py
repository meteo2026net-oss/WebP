import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from ecmwf_collector.tools.grib_to_map import _json_scalar, _json_value
from ecmwf_collector.tools.inspect_grib import KEYS, inspect_file


class GribMetadataSerializationTests(unittest.TestCase):
    def test_inventory_uses_imported_eccodes_getter_for_each_metadata_key(self):
        fake_message = object()
        values = {"edition": 2, "shortName": "msl", "units": "Pa"}
        requested = []

        def codes_get(gid, key):
            self.assertIs(gid, fake_message)
            requested.append(key)
            if key not in values:
                raise KeyError(key)
            return values[key]

        messages = iter([fake_message, None])
        fake_eccodes = types.SimpleNamespace(
            codes_get=codes_get,
            codes_grib_new_from_file=lambda stream: next(messages),
            codes_release=lambda gid: self.assertIs(gid, fake_message),
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.grib2"
            source.write_bytes(b"GRIB")
            with patch.dict("sys.modules", {"eccodes": fake_eccodes}):
                records = inspect_file(source)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["edition"], 2)
        self.assertEqual(records[0]["shortName"], "msl")
        self.assertEqual(records[0]["units"], "Pa")
        self.assertEqual(set(requested), set(KEYS))

    def test_inventory_includes_wind_reference_frame_flags(self):
        self.assertIn("uvRelativeToGrid", KEYS)
        self.assertIn("resolutionAndComponentFlags", KEYS)

    def test_datetime64_is_serialized_as_iso8601(self):
        value = np.datetime64("2026-11-04T00:00:00", "ns")
        self.assertEqual(_json_scalar(value), "2026-11-04T00:00:00.000000000")

    def test_timedelta64_is_serialized_as_readable_duration(self):
        value = np.timedelta64(6, "h")
        self.assertEqual(_json_scalar(value), "6 hours")

    def test_nat_is_serialized_as_null(self):
        self.assertIsNone(_json_scalar(np.datetime64("NaT")))
        self.assertIsNone(_json_scalar(np.timedelta64("NaT")))

    def test_zero_dimensional_datetime_coordinate_keeps_timestamp(self):
        value = np.array(np.datetime64("2026-11-04T00:00:00", "ns"))
        self.assertEqual(_json_value(value), "2026-11-04T00:00:00.000000000")

    def test_coordinate_arrays_use_same_scalar_conversion(self):
        values = np.array(
            ["2026-11-04T00:00:00", "2026-11-04T06:00:00"],
            dtype="datetime64[ns]",
        )
        self.assertEqual(
            _json_value(values),
            ["2026-11-04T00:00:00.000000000", "2026-11-04T06:00:00.000000000"],
        )


if __name__ == "__main__":
    unittest.main()
