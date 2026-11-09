"""Live PostgreSQL integration for FileAssetCatalog role enforcement.

Uses the disposable PostgreSQL database exposed by POSTGRES_STATE_ADMIN_DSN.
"""
from __future__ import annotations

import os
import unittest
import uuid

try:
    import psycopg
    from psycopg import sql
except ImportError:  # pragma: no cover - CI installs psycopg
    psycopg = None
    sql = None

from ecmwf_collector.connection_profiles import DatabaseProfile
from ecmwf_collector.file_asset_catalog import FileAsset, FileAssetCatalog, FileAssetError

ADMIN_DSN = os.environ.get("POSTGRES_STATE_ADMIN_DSN", "").strip()


class _Secrets:
    def __init__(self, password):
        self.password = password

    def get_password(self, _key):
        return self.password


@unittest.skipUnless(ADMIN_DSN and psycopg is not None, "live PostgreSQL test is not configured")
class FileAssetCatalogPostgresRoleLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.role = "webp_catalog_it_" + uuid.uuid4().hex[:12]
        cls.password = uuid.uuid4().hex + uuid.uuid4().hex
        settings = psycopg.conninfo.conninfo_to_dict(ADMIN_DSN)
        cls.database = settings.get("dbname", "postgres")
        cls.host = settings.get("host", "127.0.0.1")
        cls.port = int(settings.get("port", 5432))
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(cls.role), sql.Literal(cls.password))
            )
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(cls.database), sql.Identifier(cls.role)
                )
            )
            conn.execute(
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
                    sql.Identifier(cls.role)
                )
            )

        profile = DatabaseProfile.create(
            "Live PostgreSQL catalogue role test",
            "postgresql",
            database=cls.database,
            host=cls.host,
            port=cls.port,
            username=cls.role,
            ssl_mode="disable",
        )
        cls.catalog = FileAssetCatalog(profile, _Secrets(cls.password), timeout=5)
        # Schema creation is explicitly authorized only for this setup step.
        cls.catalog.initialize_schema()

    @classmethod
    def tearDownClass(cls):
        if not ADMIN_DSN or psycopg is None or not hasattr(cls, "role"):
            return
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            elevated = getattr(cls, "elevated_role", None)
            if elevated:
                conn.execute(
                    sql.SQL("REVOKE {} FROM {}").format(
                        sql.Identifier(elevated), sql.Identifier(cls.role)
                    )
                )
                conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(elevated)))
            conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(cls.role)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(cls.role)))

    def _asset(self):
        return FileAsset(
            provider_id="noaa_nomads",
            model_id="noaa_gfs",
            product_id="integration_test",
            local_path="integration/live.grib2",
            content_type="application/x-grib2",
            size_bytes=12,
            sha256="a" * 64,
            source_uri="https://example.invalid/live.grib2",
            validation_status="framing_checked",
            metadata_json='{"integration": true}',
        )

    def test_restricted_live_role_initializes_and_uses_catalog(self):
        connection, dialect = self.catalog._connect()
        try:
            self.assertEqual(dialect, "postgresql")
        finally:
            connection.close()
        result = self.catalog.register_asset(self._asset())
        self.assertTrue(result["source_registered"])\n        self.assertTrue(result["asset_id"])

    def test_live_role_with_database_admin_attribute_is_rejected(self):
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute(sql.SQL("ALTER ROLE {} CREATEDB").format(sql.Identifier(self.role)))
        try:
            with self.assertRaisesRegex(FileAssetError, "صلاحيات مدير"):
                self.catalog._connect()
        finally:
            with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
                conn.execute(sql.SQL("ALTER ROLE {} NOCREATEDB").format(sql.Identifier(self.role)))

    def test_live_membership_in_bypass_rls_role_is_rejected(self):
        self.elevated_role = "webp_catalog_elev_" + uuid.uuid4().hex[:10]
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute(
                sql.SQL("CREATE ROLE {} NOLOGIN BYPASSRLS").format(
                    sql.Identifier(self.elevated_role)
                )
            )
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(self.elevated_role), sql.Identifier(self.role)
                )
            )
        try:
            with self.assertRaisesRegex(FileAssetError, "عضو في دور"):
                self.catalog._connect()
        finally:
            with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
                conn.execute(
                    sql.SQL("REVOKE {} FROM {}").format(
                        sql.Identifier(self.elevated_role), sql.Identifier(self.role)
                    )
                )
                conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(self.elevated_role)))
            del self.elevated_role

    def test_live_missing_table_crud_is_rejected(self):
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute(
                sql.SQL("REVOKE SELECT ON TABLE public.webp_file_assets FROM {}").format(
                    sql.Identifier(self.role)
                )
            )
        try:
            with self.assertRaisesRegex(FileAssetError, "CRUD"):
                self.catalog._connect()
        finally:
            with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
                conn.execute(
                    sql.SQL("GRANT SELECT ON TABLE public.webp_file_assets TO {}").format(
                        sql.Identifier(self.role)
                    )
                )

    def test_live_schema_create_is_needed_only_for_explicit_initialization(self):
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute(
                sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(
                    sql.Identifier(self.role)
                )
            )
        try:
            connection, _dialect = self.catalog._connect()
            connection.close()
            with self.assertRaisesRegex(FileAssetError, "يلزم CREATE"):
                self.catalog.initialize_schema()
        finally:
            with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
                conn.execute(
                    sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(
                        sql.Identifier(self.role)
                    )
                )


if __name__ == "__main__":
    unittest.main()
