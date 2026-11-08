"""Real PostgreSQL and MySQL integration checks for file catalog + Outbox."""
import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlparse

from ecmwf_collector.asset_sync import AssetOutboxSynchronizer, OutboxSyncApproval
from ecmwf_collector.connection_profiles import DatabaseProfile, DatabaseProfileStore
from ecmwf_collector.file_asset_catalog import FileAsset, FileAssetCatalog


class _Secrets:
    def __init__(self):
        self.values = {}

    def get_password(self, key):
        return self.values[key]


def _profile(name, url, backend):
    parsed = urlparse(url)
    return DatabaseProfile.create(
        name, backend,
        database=unquote(parsed.path.lstrip("/")),
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or (3306 if backend in {"mysql", "mariadb"} else 5432),
        username=unquote(parsed.username or "root"),
        ssl_mode="disable",
    )


class ServerCatalogIntegrationTests(unittest.TestCase):
    def _exercise(self, backend, source_env, target_env):
        source_url, target_url = os.getenv(source_env), os.getenv(target_env)
        if not source_url or not target_url:
            self.skipTest(f"{source_env}/{target_env} are not configured")
        with tempfile.TemporaryDirectory() as tmp:
            store = DatabaseProfileStore(Path(tmp) / "profiles.json")
            source = _profile("integration source", source_url, backend)
            target = _profile("integration target", target_url, backend)
            store.save(source)
            store.save(target)
            secrets = _Secrets()
            secrets.values[source.credential_key] = unquote(urlparse(source_url).password or "postgres")
            secrets.values[target.credential_key] = unquote(urlparse(target_url).password or "postgres")
            source_catalog = FileAssetCatalog(source, secrets)
            target_catalog = FileAssetCatalog(target, secrets)
            source_catalog.initialize_schema()
            target_catalog.initialize_schema()
            asset = FileAsset(
                provider_id="noaa_nomads",
                model_id="noaa_gfs",
                product_id="gfs_0p25",
                local_path="ci-fixture/gfs.grib2",
                content_type="application/x-grib2",
                size_bytes=64,
                sha256="a" * 64,
                run_time_utc="2026-11-08T00:00:00Z",
                valid_time_utc="2026-11-08T06:00:00Z",
                source_uri="https://example.invalid/gfs.grib2",
                validation_status="framing_checked",
                metadata_json='{"ci":true}',
            )
            registered = source_catalog.register_asset(
                asset, replica_profile_ids=(target.profile_id,)
            )
            sync = AssetOutboxSynchronizer(
                source.profile_id, store, secrets,
                approved_target_profile_ids=(target.profile_id,),
            )
            result = sync.sync_pending(
                OutboxSyncApproval((target.profile_id,), confirmed=True)
            )
            self.assertEqual(result["delivered"], 1)
            variants = target_catalog.load_asset_variants(registered["asset_key"])
            self.assertEqual(len(variants), 1)
            self.assertEqual(variants[0].sha256, asset.sha256)
            self.assertEqual(
                source_catalog.pending_outbox(target_profile_id=target.profile_id), []
            )

    def test_postgresql_schema_register_and_outbox_sync(self):
        self._exercise("postgresql", "ASSET_PG_SOURCE_URL", "ASSET_PG_TARGET_URL")

    def test_mysql_schema_register_and_outbox_sync(self):
        self._exercise("mysql", "ASSET_MYSQL_SOURCE_URL", "ASSET_MYSQL_TARGET_URL")

    def test_mariadb_schema_register_and_outbox_sync(self):
        self._exercise("mariadb", "ASSET_MARIADB_SOURCE_URL", "ASSET_MARIADB_TARGET_URL")


if __name__ == "__main__":
    unittest.main()
