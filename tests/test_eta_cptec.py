import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecmwf_collector.sources.eta_cptec import _validate, list_eta_files


class _Response:
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size=-1):
        data, self.body = self.body, b""
        return data


class CPTECTests(unittest.TestCase):
    def test_rejects_invalid_date_and_domain(self):
        with self.assertRaises(ValueError):
            _validate("20261340", "00", "ams_08km")
        with self.assertRaises(ValueError):
            _validate("20261107", "00", "../etc")

    def test_lists_only_grib_files(self):
        html = b'<a href="model.grb2">model</a><a href="notes.txt">notes</a><a href="../">up</a>'
        def fake_open(*args, **kwargs):
            return _Response(html)
        self.assertEqual(list_eta_files("20261107", "00", "ams_08km", opener=fake_open),
                         ["model.grb2"])

    def test_download_registers_only_after_verified_sidecar(self):
        import hashlib
        import json
        from types import SimpleNamespace
        from ecmwf_collector.sources.eta_cptec import retrieve_eta_file

        payload = b"GRIB" + b"x" * 128 + b"7777"
        html = b'<a href="eta.grb2">eta</a>'

        def fake_open(request, timeout):
            return _Response(html if request.full_url.endswith("/") else payload)

        class Sink:
            def __init__(self):
                self.paths = []
            def register_sidecar(self, path):
                self.paths.append(Path(path))
                return {"asset_id": "cptec-test"}

        sink = Sink()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "eta.grb2"
            with patch("ecmwf_collector.fileinspect.inspect_file",
                       return_value=SimpleNamespace(verdict="ok", kind="grib2",
                                                     messages=1, problem=None)):
                report = retrieve_eta_file(
                    "20261107", "06", "ams_08km", "eta.grb2", target,
                    opener=fake_open, catalog_sink=sink,
                )
            sidecar = target.with_suffix(".grb2.source.json")
            self.assertEqual(sink.paths, [sidecar])
            self.assertTrue(sidecar.is_file())
            self.assertEqual(report["catalog_registration"]["asset_id"], "cptec-test")
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(metadata["sha256"], hashlib.sha256(payload).hexdigest())

    def test_directory_contract_and_domains(self):
        from ecmwf_collector.sources import eta_cptec
        self.assertIn("dataserver.cptec.inpe.br", eta_cptec.BASE_URL)
        self.assertIn("rjsp_01km", eta_cptec.DOMAINS)


if __name__ == "__main__":
    unittest.main()
