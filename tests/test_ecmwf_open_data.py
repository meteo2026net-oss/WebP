import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ecmwf_collector.sources.ecmwf_open_data import retrieve_open_data


class OpenDataTests(unittest.TestCase):
    def test_requires_param_and_step(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                retrieve_open_data({"type": "fc"}, Path(directory) / "x.grib", client_factory=object)

    def test_retrieves_validates_hashes_and_writes_sidecar(self):
        class FakeClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def retrieve(self, request, target):
                Path(target).write_bytes(b"GRIB" + b"x" * 128 + b"7777")
                return SimpleNamespace(datetime=None)

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "ifs.grib2"
            with patch(
                "ecmwf_collector.fileinspect.inspect_file",
                return_value=SimpleNamespace(
                    verdict="ok", kind="grib2", messages=1, problem=None
                ),
            ):
                report = retrieve_open_data(
                    {"param": ["2t"], "step": 6},
                    target,
                    client_factory=FakeClient,
                )
            self.assertTrue(target.is_file())
            self.assertEqual(report["integrity"], "ok")
            self.assertEqual(report["message_count"], 1)
            sidecar = target.with_suffix(".grib2.source.json")
            self.assertTrue(sidecar.is_file())
            self.assertEqual(json.loads(sidecar.read_text())["model"], "ifs")

    def test_catalog_sink_called_only_after_validation(self):
        class FakeClient:
            def __init__(self, **kwargs):
                pass

            def retrieve(self, request, target):
                Path(target).write_bytes(b"GRIB" + b"x" * 128 + b"7777")
                return SimpleNamespace(datetime=None)

        class Sink:
            def __init__(self):
                self.paths = []

            def register_sidecar(self, path):
                self.paths.append(Path(path))
                return {"asset_id": "test-asset"}

        sink = Sink()
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "ecmwf_collector.fileinspect.inspect_file",
                return_value=SimpleNamespace(
                    verdict="ok", kind="grib2", messages=1, problem=None
                ),
            ):
                report = retrieve_open_data(
                    {"param": ["2t"], "step": 6},
                    Path(directory) / "ifs.grib2",
                    client_factory=FakeClient,
                    catalog_sink=sink,
                )
            self.assertEqual(len(sink.paths), 1)
            self.assertEqual(report["catalog_registration"]["asset_id"], "test-asset")

    def test_latest_run_is_saved_with_actual_forecast_cycle(self):
        from datetime import datetime

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            def retrieve(self, request, target):
                Path(target).write_bytes(b"GRIB" + b"x" * 128 + b"7777")
                return SimpleNamespace(datetime=datetime(2026, 11, 18, 6))

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "ifs_latest_06.grib2"
            with patch(
                "ecmwf_collector.fileinspect.inspect_file",
                return_value=SimpleNamespace(
                    verdict="ok", kind="grib2", messages=1, problem=None
                ),
            ):
                report = retrieve_open_data(
                    {"param": ["2t"], "step": 6, "time": 6},
                    target,
                    client_factory=FakeClient,
                )
            actual = Path(report["path"])
            self.assertTrue(actual.is_file())
            self.assertIn("20261118T06", actual.name)
            self.assertFalse(target.exists())
            self.assertTrue(actual.with_suffix(".grib2.source.json").is_file())

    def test_aifs_single_adds_oper_stream_and_rejects_tenth_degree(self):
        class FakeClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def retrieve(self, request, target):
                self.request = request
                Path(target).write_bytes(b"GRIB" + b"x" * 128 + b"7777")
                return SimpleNamespace(datetime=None)

        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "ecmwf_collector.fileinspect.inspect_file",
                return_value=SimpleNamespace(
                    verdict="ok", kind="grib2", messages=1, problem=None
                ),
            ):
                report = retrieve_open_data(
                    {"param": ["2t"], "step": 6},
                    Path(directory) / "aifs.grib2",
                    model="aifs-single",
                    resolution="0p25",
                    client_factory=lambda **_kwargs: client,
                )
            self.assertEqual(report["request"]["stream"], "oper")
            with self.assertRaisesRegex(ValueError, "0.25"):
                retrieve_open_data(
                    {"param": ["2t"], "step": 6},
                    Path(directory) / "invalid.grib2",
                    model="aifs-single",
                    resolution="0p1",
                    client_factory=lambda **_kwargs: self.fail("Client must not be created"),
                )

    def test_rejects_invalid_grib_and_cleans_partial_file(self):
        class FakeClient:
            def __init__(self, **kwargs):
                pass

            def retrieve(self, request, target):
                Path(target).write_bytes(b"not-grib")

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bad.grib2"
            with patch(
                "ecmwf_collector.fileinspect.inspect_file",
                return_value=SimpleNamespace(
                    verdict="corrupt", kind="unknown", messages=0, problem="bad"
                ),
            ):
                with self.assertRaises(RuntimeError):
                    retrieve_open_data(
                        {"param": ["2t"], "step": 6},
                        target,
                        client_factory=FakeClient,
                    )
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name(target.name + ".part").exists())


if __name__ == "__main__":
    unittest.main()
