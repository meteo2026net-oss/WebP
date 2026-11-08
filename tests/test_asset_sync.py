import hashlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path

from ecmwf_collector.asset_sync import (
    ApprovedCatalogSink,
    AssetOutboxSynchronizer,
    CatalogApprovalError,
    CatalogWriteApproval,
    OutboxSyncApproval,
)
from ecmwf_collector.connection_profiles import DatabaseProfile, DatabaseProfileStore
from ecmwf_collector.database_routing import DatabaseRoutingStore
from ecmwf_collector.file_asset_catalog import FileAsset, FileAssetCatalog


class AssetSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.profile_store = DatabaseProfileStore(root / "profiles.json")
        self.source = DatabaseProfile.create("Primary", "sqlite", sqlite_path=str(root / "primary.db"))
        self.target = DatabaseProfile.create("Replica", "sqlite", sqlite_path=str(root / "replica.db"))
        self.profile_store.save(self.source)
        self.profile_store.save(self.target)
        self.routing = DatabaseRoutingStore(root / "routing.json", self.profile_store)
        self.route_key = self.routing.model_key("noaa_nomads", "noaa_gfs", "gfs_0p25")
        self.routing.set_route(self.route_key, self.source.profile_id)
        self.source_catalog = FileAssetCatalog(self.source)

    def query(self, path, sql, params=()):
        connection = sqlite3.connect(path)
        try:
            return connection.execute(sql, params).fetchall()
        finally:
            connection.close()

    def sample_asset(self, **changes):
        values = {
            "provider_id": "noaa_nomads",
            "model_id": "noaa_gfs",
            "product_id": "gfs_0p25",
            "local_path": "downloads/gfs.grib2",
            "content_type": "application/x-grib2",
            "size_bytes": 128,
            "sha256": hashlib.sha256(b"sample-file").hexdigest(),
            "run_time_utc": "2026-11-08T00:00:00Z",
            "valid_time_utc": "2026-11-08T06:00:00Z",
            "source_uri": "https://nomads.example/gfs.grib2",
            "validation_status": "framing_checked",
            "metadata_json": json.dumps({"variables": ["TMP"]}),
        }
        values.update(changes)
        return FileAsset(**values)

    def make_sidecar(self):
        root = Path(self.temp.name)
        data = b"GRIB" + b"payload" + b"7777"
        grib = root / "gfs.grib2"
        grib.write_bytes(data)
        sidecar = root / "gfs.grib2.source.json"
        sidecar.write_text(json.dumps({
            "source": "NOAA/NCEP NOMADS",
            "model": "GFS",
            "file_name": grib.name,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "source_url": "https://nomads.example/gfs.grib2",
            "resolution": "0p25",
            "run": "2026-11-08T00:00:00Z",
            "valid_time": "2026-11-08T06:00:00Z",
            "integrity": "GRIB2 framing checked; SHA-256 recorded",
        }), encoding="utf-8")
        return sidecar

    def test_register_and_outbox_enqueue_are_one_transaction(self):
        self.source_catalog.initialize_schema()
        result = self.source_catalog.register_asset(
            self.sample_asset(), replica_profile_ids=[self.target.profile_id]
        )
        self.assertEqual(result["outbox_enqueued"], 1)
        rows = self.source_catalog.pending_outbox()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_profile_id"], self.target.profile_id)

    def test_outbox_preserves_multiple_source_uris(self):
        self.source_catalog.initialize_schema()
        self.source_catalog.register_asset(
            self.sample_asset(source_uri="https://mirror-a.example/a"),
            replica_profile_ids=[self.target.profile_id],
        )
        self.source_catalog.register_asset(
            self.sample_asset(source_uri="https://mirror-b.example/a"),
            replica_profile_ids=[self.target.profile_id],
        )
        variants = self.source_catalog.load_asset_variants(
            self.source_catalog.pending_outbox()[0]["asset_key"]
        )
        self.assertEqual({a.source_uri for a in variants}, {
            "https://mirror-a.example/a", "https://mirror-b.example/a"
        })

    def test_sync_requires_explicit_confirmation(self):
        self.source_catalog.initialize_schema()
        self.source_catalog.register_asset(
            self.sample_asset(), replica_profile_ids=[self.target.profile_id]
        )
        sync = AssetOutboxSynchronizer(self.source.profile_id, self.profile_store, None, approved_target_profile_ids=(self.target.profile_id,))
        with self.assertRaises(CatalogApprovalError):
            sync.sync_pending(OutboxSyncApproval((self.target.profile_id,), confirmed=False))

    def test_sync_retries_after_target_schema_is_initialized(self):
        self.source_catalog.initialize_schema()
        self.source_catalog.register_asset(
            self.sample_asset(), replica_profile_ids=[self.target.profile_id]
        )
        sync = AssetOutboxSynchronizer(self.source.profile_id, self.profile_store, None, approved_target_profile_ids=(self.target.profile_id,))
        approval = OutboxSyncApproval((self.target.profile_id,), confirmed=True)
        first = sync.sync_pending(approval)
        self.assertEqual(first["failed"], 1)
        FileAssetCatalog(self.target).initialize_schema()
        second = sync.sync_pending(approval)
        self.assertEqual(second["delivered"], 1)
        self.assertEqual(
            self.query(self.target.sqlite_path, "SELECT COUNT(*) FROM webp_file_assets")[0][0], 1
        )
        self.assertEqual(
            self.query(self.source.sqlite_path, "SELECT status FROM webp_asset_outbox")[0][0],
            "delivered",
        )

    def test_sync_rejects_target_not_in_session_approval(self):
        self.source_catalog.initialize_schema()
        self.source_catalog.register_asset(
            self.sample_asset(), replica_profile_ids=[self.target.profile_id]
        )
        sync = AssetOutboxSynchronizer(
            self.source.profile_id, self.profile_store, None,
            approved_target_profile_ids=(),
        )
        with self.assertRaises(CatalogApprovalError):
            sync.sync_pending(
                OutboxSyncApproval((self.target.profile_id,), confirmed=True)
            )

    def test_sync_is_idempotent_if_target_commit_precedes_source_ack(self):
        self.source_catalog.initialize_schema()
        FileAssetCatalog(self.target).initialize_schema()
        asset = self.sample_asset()
        self.source_catalog.register_asset(asset, replica_profile_ids=[self.target.profile_id])
        # Simulate a crash after the target committed but before source Outbox ack.
        FileAssetCatalog(self.target).register_asset(asset)
        sync = AssetOutboxSynchronizer(self.source.profile_id, self.profile_store, None, approved_target_profile_ids=(self.target.profile_id,))
        result = sync.sync_pending(
            OutboxSyncApproval((self.target.profile_id,), confirmed=True)
        )
        self.assertEqual(result["delivered"], 1)
        self.assertEqual(
            self.query(self.target.sqlite_path, "SELECT COUNT(*) FROM webp_file_assets")[0][0], 1
        )

    def test_delivered_outbox_event_cannot_regress_after_late_failure(self):
        self.source_catalog.initialize_schema()
        self.source_catalog.register_asset(
            self.sample_asset(), replica_profile_ids=[self.target.profile_id]
        )
        event_id = self.source_catalog.pending_outbox()[0]["event_id"]

        self.source_catalog.finish_outbox(event_id, delivered=True)
        self.source_catalog.finish_outbox(
            event_id, delivered=False, error="late concurrent failure"
        )

        rows = self.query(
            self.source.sqlite_path,
            "SELECT status, attempts, last_error FROM webp_asset_outbox WHERE event_id=?",
            (event_id,),
        )
        self.assertEqual(rows, [("delivered", 1, None)])

    def test_two_independent_outbox_workers_race_on_same_event(self):
        self.source_catalog.initialize_schema()
        self.source_catalog.register_asset(
            self.sample_asset(), replica_profile_ids=[self.target.profile_id]
        )

        barrier = Barrier(2)
        workers = [
            AssetOutboxSynchronizer(
                self.source.profile_id, self.profile_store, None,
                approved_target_profile_ids=(self.target.profile_id,),
            )
            for _ in range(2)
        ]
        for worker in workers:
            original_pending = worker.source_catalog.pending_outbox

            def synchronized_pending(*, target_profile_id=None, limit=100,
                                     _original=original_pending):
                events = _original(target_profile_id=target_profile_id, limit=limit)
                barrier.wait(timeout=10)
                return events

            worker.source_catalog.pending_outbox = synchronized_pending

        approval = OutboxSyncApproval((self.target.profile_id,), confirmed=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda worker: worker.sync_pending(approval), workers))

        statuses = self.query(
            self.source.sqlite_path,
            "SELECT status, attempts FROM webp_asset_outbox",
        )
        target_count = self.query(
            self.target.sqlite_path,
            "SELECT COUNT(*) FROM webp_file_assets",
        )[0][0]
        self.assertEqual(statuses[0][0], "delivered")
        self.assertEqual(statuses[0][1], 1)
        self.assertEqual(target_count, 1)
        self.assertGreaterEqual(sum(item["delivered"] for item in results), 1)
        self.assertEqual(sum(item["delivered"] + item["failed"] + item["skipped"] for item in results), 2)

    def test_approved_sink_requires_exact_route_and_destination(self):
        with self.assertRaises(CatalogApprovalError):
            ApprovedCatalogSink(
                self.profile_store, self.routing, None,
                CatalogWriteApproval(self.route_key, self.source.profile_id, (self.source.profile_id,), (), False),
            )
        sink = ApprovedCatalogSink(
            self.profile_store, self.routing, None,
            CatalogWriteApproval(
                self.route_key,
                self.source.profile_id,
                (self.source.profile_id, self.target.profile_id),
                (self.target.profile_id,),
                True,
            ),
        )
        result = sink.register_sidecar(self.make_sidecar())
        self.assertEqual(result["outbox_enqueued"], 1)
        self.assertEqual(len(self.source_catalog.pending_outbox()), 1)
        self.assertTrue(Path(self.source.sqlite_path).exists())
        self.assertTrue(Path(self.target.sqlite_path).exists())

    def test_default_route_is_not_a_substitute_for_explicit_model_route(self):
        self.routing.clear_route(self.route_key)
        self.routing.set_default(self.source.profile_id)
        with self.assertRaises(CatalogApprovalError):
            ApprovedCatalogSink(
                self.profile_store, self.routing, None,
                CatalogWriteApproval(self.route_key, self.source.profile_id, (self.source.profile_id,), (), True),
            )
        self.assertFalse(Path(self.source.sqlite_path).exists())

    def test_outbox_insert_failure_rolls_back_asset_registration(self):
        self.source_catalog.initialize_schema()
        connection = sqlite3.connect(self.source.sqlite_path)
        try:
            connection.execute("""
                CREATE TRIGGER reject_outbox BEFORE INSERT ON webp_asset_outbox
                BEGIN SELECT RAISE(ABORT, 'test outbox failure'); END
            """)
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(Exception):
            self.source_catalog.register_asset(
                self.sample_asset(), replica_profile_ids=[self.target.profile_id]
            )
        self.assertEqual(
            self.query(self.source.sqlite_path, "SELECT COUNT(*) FROM webp_file_assets")[0][0], 0
        )
        self.assertEqual(
            self.query(self.source.sqlite_path, "SELECT COUNT(*) FROM webp_asset_outbox")[0][0], 0
        )

    def test_missing_explicit_route_fails_before_schema_creation(self):
        self.routing.clear_route(self.route_key)
        with self.assertRaises(CatalogApprovalError):
            ApprovedCatalogSink(
                self.profile_store, self.routing, None,
                CatalogWriteApproval(self.route_key, self.source.profile_id, (self.source.profile_id,), (), True),
            )
        self.assertFalse(Path(self.source.sqlite_path).exists())


if __name__ == "__main__":
    unittest.main()
