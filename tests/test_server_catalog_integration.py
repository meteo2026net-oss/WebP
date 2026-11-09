"""Real PostgreSQL and MySQL integration checks for file catalog + Outbox."""
import os
import select
import socket
import socketserver
import tempfile
import threading
import unittest
from unittest.mock import patch
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


class _DropOnceTcpProxy:
    """A local TCP relay that can reset exactly one incoming DB connection."""

    def __init__(self, upstream_host, upstream_port):
        owner = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                with owner._lock:
                    should_drop = owner._drop_next
                    if should_drop:
                        owner._drop_next = False
                if should_drop:
                    try:
                        self.request.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    return

                try:
                    upstream = socket.create_connection(
                        (owner.upstream_host, owner.upstream_port), timeout=5
                    )
                except OSError:
                    return
                with upstream:
                    sockets = (self.request, upstream)
                    while True:
                        try:
                            readable, _, exceptional = select.select(
                                sockets, (), sockets, 10
                            )
                            if exceptional or not readable:
                                return
                            for source in readable:
                                data = source.recv(65536)
                                if not data:
                                    return
                                destination = upstream if source is self.request else self.request
                                destination.sendall(data)
                        except OSError:
                            return

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self._lock = threading.Lock()
        self._drop_next = False
        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def drop_next_connection(self):
        with self._lock:
            self._drop_next = True


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


    def test_mariadb_outbox_recovers_after_real_tcp_drop_before_source_ack(self):
        source_url = os.getenv("ASSET_MARIADB_SOURCE_URL")
        target_url = os.getenv("ASSET_MARIADB_TARGET_URL")
        if not source_url or not target_url:
            self.skipTest("MariaDB integration URLs are not configured")

        parsed_source = urlparse(source_url)
        upstream_host = parsed_source.hostname or "127.0.0.1"
        upstream_port = parsed_source.port or 3306
        with tempfile.TemporaryDirectory() as tmp, _DropOnceTcpProxy(
            upstream_host, upstream_port
        ) as proxy:
            store = DatabaseProfileStore(Path(tmp) / "profiles.json")
            source_base = _profile("MariaDB proxied source", source_url, "mariadb")
            source = DatabaseProfile.create(
                "MariaDB TCP-proxied source", "mariadb",
                database=source_base.database, host="127.0.0.1", port=proxy.port,
                username=source_base.username, ssl_mode="disable",
            )
            target = _profile("MariaDB direct target", target_url, "mariadb")
            store.save(source)
            store.save(target)

            secrets = _Secrets()
            secrets.values[source.credential_key] = unquote(parsed_source.password or "mariadb")
            secrets.values[target.credential_key] = unquote(urlparse(target_url).password or "mariadb")
            source_catalog = FileAssetCatalog(source, secrets)
            target_catalog = FileAssetCatalog(target, secrets)
            source_catalog.initialize_schema()
            target_catalog.initialize_schema()

            asset = FileAsset(
                provider_id="noaa_nomads", model_id="noaa_gfs",
                product_id="gfs_0p25", local_path="ci-fixture/tcp-drop.grib2",
                content_type="application/x-grib2", size_bytes=64,
                sha256="b" * 64, run_time_utc="2026-11-08T00:00:00Z",
                valid_time_utc="2026-11-08T06:00:00Z",
                source_uri="https://example.invalid/tcp-drop.grib2",
                validation_status="framing_checked", metadata_json='{"ci":true,"tcp_drop":true}',
            )
            source_catalog.register_asset(
                asset, replica_profile_ids=(target.profile_id,)
            )
            sync = AssetOutboxSynchronizer(
                source.profile_id, store, secrets,
                approved_target_profile_ids=(target.profile_id,),
            )
            approval = OutboxSyncApproval((target.profile_id,), confirmed=True)
            original_finish = FileAssetCatalog.finish_outbox
            dropped = {"once": False}

            def drop_source_ack(catalog, event_id, *, delivered, error=None):
                if (
                    catalog.profile.profile_id == source.profile_id
                    and delivered and not dropped["once"]
                ):
                    dropped["once"] = True
                    proxy.drop_next_connection()
                return original_finish(
                    catalog, event_id, delivered=delivered, error=error
                )

            with patch.object(FileAssetCatalog, "finish_outbox", new=drop_source_ack):
                first = sync.sync_pending(approval)

            self.assertTrue(dropped["once"], "the TCP proxy did not inject the disconnect")
            self.assertEqual(first["failed"], 1)
            self.assertEqual(
                target_catalog.load_asset_variants(
                    source_catalog.pending_outbox()[0]["asset_key"]
                )[0].sha256,
                asset.sha256,
            )

            second = sync.sync_pending(approval)
            self.assertEqual(second["delivered"], 1)
            self.assertEqual(
                source_catalog.pending_outbox(target_profile_id=target.profile_id), []
            )
            self.assertEqual(
                len(target_catalog.load_asset_variants(
                    source_catalog.load_asset_variants(
                        source_catalog.pending_outbox(limit=1)[0]["asset_key"]
                    )[0].sha256
                )),
                1,
            )


if __name__ == "__main__":
    unittest.main()
