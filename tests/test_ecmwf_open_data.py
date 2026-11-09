import tempfile, unittest
from pathlib import Path
from ecmwf_collector.sources.ecmwf_open_data import retrieve_open_data

class OpenDataTests(unittest.TestCase):
    def test_requires_param_and_step(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                retrieve_open_data({"type":"fc"},Path(d)/"x.grib",client_factory=object)
    def test_catalog_sink_receives_sidecar_after_validation(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch

        class FakeClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
            def retrieve(self, request, target):
                Path(target).write_bytes(b"GRIB" + b"x" * 128 + b"7777")
                return SimpleNamespace(datetime=None)

        class Sink:
            def __init__(self):
                self.paths = []
            def register_sidecar(self, path):
                self.paths.append(Path(path))
                return {"asset_id": "fake"}

        sink = Sink()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "ifs.grib"
            with patch("ecmwf_collector.fileinspect.inspect_file",
                       return_value=SimpleNamespace(verdict="ok", kind="grib2",
                                                     messages=1, problem=None)):
                report = retrieve_open_data(
                    {"param": ["2t"], "step": 6}, target,
                    client_factory=FakeClient, catalog_sink=sink,
                )
            self.assertEqual(len(sink.paths), 1)
            self.assertTrue(sink.paths[0].is_file())
            self.assertEqual(json.loads(sink.paths[0].read_text())["model"], "ifs")
            self.assertEqual(report["catalog_registration"]["asset_id"], "fake")

    def test_source_metadata_contract(self):
        # Keep the contract test independent from network and ECMWF availability.
        from ecmwf_collector.sources import ecmwf_open_data
        self.assertEqual(ecmwf_open_data.__doc__.split(";")[0],"ECMWF Open Data client")
        self.assertTrue(callable(retrieve_open_data))
if __name__=="__main__": unittest.main()
