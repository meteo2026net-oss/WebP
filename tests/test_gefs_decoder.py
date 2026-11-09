"""Tests for GRIB field decoding and ensemble compatibility gates."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

from ecmwf_collector.gefs_decoder import (
    DecodedGefsField, GefsGribDecodeError, decode_gefs_ensemble_fields,
    decode_gefs_grib_field, calculate_gefs_ensemble_statistics,
)

class FakeValue:
    def __init__(self, values, attrs=None):
        self.values = np.asarray(values)
        self.attrs = attrs or {}

class FakeDataset:
    def __init__(self, variable, coords):
        self.data_vars = {"field": variable}
        self.coords = {key: FakeValue(value) for key, value in coords.items()}
        self.closed = False
    def close(self):
        self.closed = True

def fake_field(*, lon=(30.0, 31.0), units="K", run="2026-11-07T00:00:00", valid="2026-11-08T00:00:00"):
    variable = FakeValue([[270.0, 271.0], [272.0, 273.0]], {
        "GRIB_shortName": "t", "GRIB_typeOfLevel": "heightAboveGround",
        "GRIB_level": 2, "units": units,
    })
    dataset = FakeDataset(variable, {
        "latitude": [[51.0, 51.0], [52.0, 52.0]],
        "longitude": [list(lon), list(lon)],
        "time": np.datetime64(run), "valid_time": np.datetime64(valid),
        "step": np.timedelta64(24, "h"),
    })
    return dataset

class GefsDecoderTests(unittest.TestCase):
    def test_decodes_exact_field_and_closes_dataset(self):
        dataset = fake_field()
        with patch("ecmwf_collector.gefs_decoder._open_cfgrib_datasets", return_value=[dataset]):
            result = decode_gefs_grib_field("member.grib2", short_name="t", type_of_level="heightAboveGround", level=2)
        self.assertEqual(result.units, "K")
        self.assertEqual(result.forecast_hour, 24)
        self.assertEqual(result.valid_time, "2026-11-08T00:00:00Z")
        self.assertTrue(dataset.closed)

    def test_matches_level_from_cfgrib_dataset_coordinate_when_attribute_absent(self):
        dataset = fake_field()
        dataset.data_vars["field"].attrs.pop("GRIB_level")
        dataset.coords["heightAboveGround"] = FakeValue(2.0)
        with patch("ecmwf_collector.gefs_decoder._open_cfgrib_datasets", return_value=[dataset]):
            result = decode_gefs_grib_field(
                "member.grib2", short_name="t", type_of_level="heightAboveGround", level=2
            )
        self.assertEqual(result.units, "K")
        self.assertTrue(dataset.closed)

    def test_rejects_extra_non_horizontal_dimensions(self):
        dataset = fake_field()
        dataset.data_vars["field"].values = np.zeros((1, 2, 2))
        with patch("ecmwf_collector.gefs_decoder._open_cfgrib_datasets", return_value=[dataset]):
            with self.assertRaisesRegex(GefsGribDecodeError, "two-dimensional horizontal field"):
                decode_gefs_grib_field("member.grib2", short_name="t", type_of_level="heightAboveGround", level=2)

    def test_rejects_non_finite_grid_coordinates(self):
        dataset = fake_field()
        dataset.coords["latitude"].values[0, 0] = np.nan
        with patch("ecmwf_collector.gefs_decoder._open_cfgrib_datasets", return_value=[dataset]):
            with self.assertRaisesRegex(GefsGribDecodeError, "non-finite"):
                decode_gefs_grib_field("member.grib2", short_name="t", type_of_level="heightAboveGround", level=2)

    def test_rejects_fractional_forecast_hour(self):
        dataset = fake_field()
        dataset.coords["step"].values = np.asarray(np.timedelta64(90, "m"))
        with patch("ecmwf_collector.gefs_decoder._open_cfgrib_datasets", return_value=[dataset]):
            with self.assertRaisesRegex(GefsGribDecodeError, "whole number of hours"):
                decode_gefs_grib_field("member.grib2", short_name="t", type_of_level="heightAboveGround", level=2)

    def test_rejects_negative_forecast_hour(self):
        dataset = fake_field()
        dataset.coords["step"].values = np.asarray(np.timedelta64(-1, "h"))
        with patch("ecmwf_collector.gefs_decoder._open_cfgrib_datasets", return_value=[dataset]):
            with self.assertRaisesRegex(GefsGribDecodeError, "non-negative"):
                decode_gefs_grib_field("member.grib2", short_name="t", type_of_level="heightAboveGround", level=2)

    def test_rejects_inconsistent_valid_time_and_forecast_step(self):
        dataset = fake_field(valid="2026-11-08T01:00:00")
        with patch("ecmwf_collector.gefs_decoder._open_cfgrib_datasets", return_value=[dataset]):
            with self.assertRaisesRegex(GefsGribDecodeError, "valid_time does not equal"):
                decode_gefs_grib_field("member.grib2", short_name="t", type_of_level="heightAboveGround", level=2)

    def test_rejects_non_finite_requested_level(self):
        dataset = fake_field()
        with patch("ecmwf_collector.gefs_decoder._open_cfgrib_datasets", return_value=[dataset]):
            with self.assertRaisesRegex(GefsGribDecodeError, "must be finite"):
                decode_gefs_grib_field("member.grib2", short_name="t", type_of_level="heightAboveGround", level=float("nan"))

    def test_rejects_missing_exact_field(self):
        dataset = fake_field()
        with patch("ecmwf_collector.gefs_decoder._open_cfgrib_datasets", return_value=[dataset]):
            with self.assertRaisesRegex(GefsGribDecodeError, "found 0"):
                decode_gefs_grib_field("member.grib2", short_name="u", type_of_level="heightAboveGround", level=2)

    def _make_members(self, root):
        paths = []
        for member in ("c00", "p01"):
            path = root / f"gefs_{member}.grib2"
            path.write_bytes(b"GRIB" + b"x" * 12 + b"7777")
            import hashlib
            payload = {
                "source": "NOAA/NCEP NOMADS", "model": "GEFS", "member": member,
                "run": "20261107T00:00:00Z", "forecast_hour": 24,
                "valid_time": "2026-11-08T00:00:00Z", "variables": ["TMP"],
                "levels": ["2_m_above_ground"], "resolution": "0p50", "file_name": path.name,
                "size_bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            path.with_name(path.stem + ".source.json").write_text(json.dumps(payload), encoding="utf-8")
            paths.append(path)
        return paths

    def test_ensemble_accepts_identical_grids_and_units(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._make_members(Path(directory))
            with patch("ecmwf_collector.gefs_decoder._open_cfgrib_datasets", side_effect=[[fake_field()], [fake_field()]]):
                fields, metadata = decode_gefs_ensemble_fields(paths, short_name="t", type_of_level="heightAboveGround", level=2)
        self.assertEqual(set(fields), {"c00", "p01"})
        self.assertEqual(metadata["units"], "K")

    def test_ensemble_rejects_grid_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._make_members(Path(directory))
            with patch("ecmwf_collector.gefs_decoder._open_cfgrib_datasets", side_effect=[[fake_field()], [fake_field(lon=(30.0, 32.0))]]):
                with self.assertRaisesRegex(GefsGribDecodeError, "longitude grid differs"):
                    decode_gefs_ensemble_fields(paths, short_name="t", type_of_level="heightAboveGround", level=2)

    def test_integrated_statistics_run_only_after_decoder_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._make_members(Path(directory))
            with patch("ecmwf_collector.gefs_decoder._open_cfgrib_datasets", side_effect=[[fake_field()], [fake_field()]]):
                stats, metadata = calculate_gefs_ensemble_statistics(
                    paths, short_name="t", type_of_level="heightAboveGround", level=2, threshold=271.0
                )
        np.testing.assert_allclose(stats["mean"], [[270.0, 271.0], [272.0, 273.0]])
        np.testing.assert_allclose(stats["probability_exceeding_threshold_percent"], [[0.0, 0.0], [100.0, 100.0]])
        self.assertEqual(metadata["units"], "K")
    def test_ensemble_rejects_unit_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = self._make_members(Path(directory))
            with patch("ecmwf_collector.gefs_decoder._open_cfgrib_datasets", side_effect=[[fake_field()], [fake_field(units="C")]]):
                with self.assertRaisesRegex(GefsGribDecodeError, "units"):
                    decode_gefs_ensemble_fields(paths, short_name="t", type_of_level="heightAboveGround", level=2)

if __name__ == "__main__":
    unittest.main()