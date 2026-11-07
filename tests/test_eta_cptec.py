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

    def test_directory_contract_and_domains(self):
        from ecmwf_collector.sources import eta_cptec
        self.assertIn("dataserver.cptec.inpe.br", eta_cptec.BASE_URL)
        self.assertIn("rjsp_01km", eta_cptec.DOMAINS)


if __name__ == "__main__":
    unittest.main()
