import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from ecmwf_collector.tools.catalog_grib import build_catalog, is_candidate, product_type, sha256_file

class GribCatalogTests(unittest.TestCase):
    def test_product_type_recognizes_only_four_delivery_prefixes(self):
        self.assertEqual(product_type("FSD11051200110903001"), "FSD")
        self.assertEqual(product_type("FPD-file"), "FPD")
        self.assertEqual(product_type("AND-file"), "AND")
        self.assertEqual(product_type("FMD-file"), "FMD")
        self.assertEqual(product_type("unknown-file"), "OTHER")

    def test_candidate_filter_excludes_partial_files_and_keeps_extensionless_products(self):
        self.assertTrue(is_candidate(Path("FMD11060000110600011")))
        self.assertTrue(is_candidate(Path("surface.grib2")))
        self.assertFalse(is_candidate(Path("FMD11060000110600011.part")))
        self.assertFalse(is_candidate(Path("database.sqlite")))

    def test_sha256_is_streamed_and_matches_standard_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample"
            payload = b"weather-data" * 1000
            path.write_bytes(payload)
            self.assertEqual(sha256_file(path, chunk_size=17), hashlib.sha256(payload).hexdigest())

    def test_catalog_groups_files_and_marks_exact_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "FSD-one").write_bytes(b"same-content")
            (root / "FPD-two").write_bytes(b"same-content")
            (root / "AND-three").write_bytes(b"different")
            binary = SimpleNamespace(kind="unknown", detected_type="unknown",
                                     verdict="unverified", messages=0, problem="not GRIB")
            with patch("ecmwf_collector.tools.catalog_grib.inspect_binary", return_value=binary):
                report = build_catalog(root, decode_metadata=False)
        self.assertEqual(report["totals"]["files"], 3)
        self.assertEqual(report["totals"]["unique_files"], 2)
        self.assertEqual(report["totals"]["duplicates"], 1)
        self.assertEqual(report["by_product_type"]["FSD"]["duplicates"], 1)
        self.assertIsNone(report["files"][1]["duplicate_of"])
        self.assertEqual(report["files"][2]["duplicate_of"], "FPD-two")

    def test_catalog_records_message_metadata_when_available(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "FPD-sample").write_bytes(b"grib")
            binary = SimpleNamespace(kind="grib1", detected_type="GRIB1",
                                     verdict="ok", messages=1, problem="")
            records = [{"edition": 1, "shortName": "t", "name": "Temperature",
                        "units": "K", "paramId": 130, "typeOfLevel": "isobaricInhPa",
                        "level": 850, "validityDate": 20261104, "validityTime": 1800}]
            with patch("ecmwf_collector.tools.catalog_grib.inspect_binary", return_value=binary), \
                 patch("ecmwf_collector.tools.catalog_grib.inspect_messages", return_value=records):
                report = build_catalog(root, decode_metadata=True)
        metadata = report["files"][0]["metadata"]
        self.assertEqual(metadata["fields"]["shortName"], ["t"])
        self.assertEqual(metadata["fields"]["level"], ["850"])
        self.assertEqual(metadata["valid_times_utc"], ["20261104T1800Z"])

if __name__ == "__main__":
    unittest.main()
