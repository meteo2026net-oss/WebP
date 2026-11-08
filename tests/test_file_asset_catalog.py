import hashlib
import sqlite3
import json
import tempfile
import unittest
from pathlib import Path

from ecmwf_collector.connection_profiles import DatabaseProfile
from ecmwf_collector.file_asset_catalog import (FileAsset, FileAssetCatalog, FileAssetError, asset_from_sidecar)


class FileAssetCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "assets.sqlite"
        self.profile = DatabaseProfile.create(
            "Asset test", "sqlite", sqlite_path=str(self.db_path)
        )
        self.catalog = FileAssetCatalog(self.profile)

    def query(self, sql, params=()):
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(sql, params).fetchall()
        finally:
            connection.close()

    def asset(self, **overrides):
        values = {
            "provider_id": "noaa_nomads",
            "model_id": "noaa_gfs",
            "product_id": "surface_0p25",
            "local_path": "downloads/gfs.grib2",
            "content_type": "application/x-grib2",
            "size_bytes": 1024,
            "sha256": hashlib.sha256(b"sample grib bytes").hexdigest(),
            "run_time_utc": "2026-11-08T00:00:00Z",
            "valid_time_utc": "2026-11-08T06:00:00Z",
            "member_id": None,
            "source_uri": "https://nomads.example/gfs.grib2",
            "validation_status": "framing_checked",
            "metadata_json": json.dumps({"variables": ["TMP", "UGRD"]}),
        }
        values.update(overrides)
        return FileAsset(**values)

    def test_constructor_does_not_create_database_or_schema(self):
        self.assertFalse(self.db_path.exists())

    def test_explicit_schema_creation_and_idempotent_register(self):
        self.catalog.initialize_schema()
        first = self.catalog.register_asset(self.asset())
        second = self.catalog.register_asset(self.asset())
        self.assertEqual(first["asset_id"], second["asset_id"])
        self.assertEqual(self.query("SELECT COUNT(*) FROM webp_file_assets")[0][0], 1)
        self.assertEqual(self.query("SELECT COUNT(*) FROM webp_file_asset_sources")[0][0], 1)

    def test_same_content_from_two_uris_keeps_both_provenance_sources(self):
        self.catalog.initialize_schema()
        first = self.catalog.register_asset(self.asset(source_uri="https://mirror-a.example/a.grib2"))
        second = self.catalog.register_asset(self.asset(source_uri="https://mirror-b.example/a.grib2"))
        self.assertEqual(first["asset_id"], second["asset_id"])
        self.assertEqual(self.query("SELECT COUNT(*) FROM webp_file_assets")[0][0], 1)
        self.assertEqual(self.query("SELECT COUNT(*) FROM webp_file_asset_sources")[0][0], 2)

    def test_different_model_or_product_or_run_is_not_merged(self):
        self.catalog.initialize_schema()
        self.catalog.register_asset(self.asset())
        self.catalog.register_asset(self.asset(model_id="ecmwf_ifs_hres"))
        self.catalog.register_asset(self.asset(product_id="pressure_levels"))
        self.catalog.register_asset(self.asset(run_time_utc="2026-11-08T12:00:00Z"))
        self.assertEqual(self.query("SELECT COUNT(*) FROM webp_file_assets")[0][0], 4)

    def test_invalid_sha256_is_rejected_before_database_access(self):
        with self.assertRaises(FileAssetError):
            self.catalog.register_asset(self.asset(sha256="not-a-hash"))
        self.assertFalse(self.db_path.exists())

    def test_disabled_profile_fails_closed(self):
        disabled = DatabaseProfile(**{**self.profile.to_metadata(), "enabled": False})
        catalog = FileAssetCatalog(disabled)
        with self.assertRaises(FileAssetError):
            catalog.initialize_schema()
        self.assertFalse(self.db_path.exists())

    def test_noaa_sidecar_is_verified_and_normalized_without_guessing(self):
        root = Path(self.temp.name)
        data = b"GRIB" + b"sample-payload" + b"7777"
        grib = root / "gfs.grib2"
        grib.write_bytes(data)
        metadata = {
            "source": "NOAA/NCEP NOMADS",
            "model": "GFS",
            "product": "0.25 degree GRIB2 filtered subset",
            "run": "2026-11-08T00:00:00Z",
            "valid_time": "2026-11-08T06:00:00Z",
            "file_name": grib.name,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "source_url": "https://nomads.example/gfs.grib2",
            "resolution": "0p25",
            "integrity": "GRIB2 framing checked; SHA-256 recorded",
        }
        sidecar = root / "gfs.grib2.source.json"
        sidecar.write_text(json.dumps(metadata), encoding="utf-8")
        asset = asset_from_sidecar(sidecar)
        self.assertEqual(asset.provider_id, "noaa_nomads")
        self.assertEqual(asset.model_id, "noaa_gfs")
        self.assertEqual(asset.product_id, "gfs_0p25")
        self.assertEqual(asset.sha256, metadata["sha256"])
        self.assertEqual(asset.run_time_utc, metadata["run"])

    def test_sidecar_hash_mismatch_is_rejected(self):
        root = Path(self.temp.name)
        grib = root / "sample.grib2"
        grib.write_bytes(b"actual-data")
        sidecar = root / "sample.grib2.source.json"
        sidecar.write_text(json.dumps({
            "source": "NOAA/NCEP NOMADS", "model": "GFS",
            "file_name": grib.name, "size_bytes": grib.stat().st_size,
            "sha256": hashlib.sha256(b"different-data").hexdigest(),
            "resolution": "0p25",
        }), encoding="utf-8")
        with self.assertRaises(FileAssetError):
            asset_from_sidecar(sidecar)

    def test_cptec_sidecar_normalizes_full_run_timestamp(self):
        root = Path(self.temp.name)
        data = b"GRIB" + b"eta-payload" + b"7777"
        grib = root / "eta.grb2"
        grib.write_bytes(data)
        sidecar = root / "eta.grb2.source.json"
        sidecar.write_text(json.dumps({
            "source": "CPTEC_INPE_ETA",
            "domain": "ams_08km",
            "date": "20261107",
            "cycle_utc": "06",
            "filename": grib.name,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "url": "https://dataserver.cptec.inpe.br/eta.grb2",
            "integrity": "ok",
        }), encoding="utf-8")
        asset = asset_from_sidecar(sidecar)
        self.assertEqual(asset.provider_id, "cptec_inpe")
        self.assertEqual(asset.model_id, "cptec_eta")
        self.assertEqual(asset.product_id, "eta_ams_08km")
        self.assertEqual(asset.run_time_utc, "2026-11-07T06:00:00Z")

    def test_unknown_sidecar_model_is_rejected(self):
        root = Path(self.temp.name)
        grib = root / "unknown.grib2"
        grib.write_bytes(b"GRIB-data")
        sidecar = root / "unknown.grib2.source.json"
        sidecar.write_text(json.dumps({
            "source": "NOAA/NCEP NOMADS", "model": "UNRECOGNIZED",
            "file_name": grib.name, "size_bytes": grib.stat().st_size,
            "sha256": hashlib.sha256(b"GRIB-data").hexdigest(),
            "integrity": "GRIB2 framing checked; SHA-256 recorded",
        }), encoding="utf-8")
        with self.assertRaises(FileAssetError):
            asset_from_sidecar(sidecar)

    def test_source_registration_failure_rolls_back_asset(self):
        self.catalog.initialize_schema()
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("""
                CREATE TRIGGER reject_source BEFORE INSERT ON webp_file_asset_sources
                BEGIN SELECT RAISE(ABORT, 'test source failure'); END
            """)
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(Exception):
            self.catalog.register_asset(self.asset())
        self.assertEqual(self.query("SELECT COUNT(*) FROM webp_file_assets")[0][0], 0)


if __name__ == "__main__":
    unittest.main()
