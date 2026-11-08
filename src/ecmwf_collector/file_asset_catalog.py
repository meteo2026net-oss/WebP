"""Portable, explicit file-asset catalogue for downloaded meteorological files.

This catalogue stores file provenance and integrity metadata only. It does not
parse GRIB messages into meteorological observations and never initializes a
schema until initialize_schema() is called explicitly by the user/application.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_TEXT = ("provider_id", "model_id", "product_id", "local_path", "content_type")


class FileAssetError(ValueError):
    """Invalid asset metadata or an unsafe catalogue operation."""


@dataclass(frozen=True)
class FileAsset:
    provider_id: str
    model_id: str
    product_id: str
    local_path: str
    content_type: str
    size_bytes: int
    sha256: str
    run_time_utc: str | None = None
    valid_time_utc: str | None = None
    member_id: str | None = None
    source_uri: str | None = None
    validation_status: str = "unverified"
    metadata_json: str = "{}"

    def validate(self) -> None:
        for field in _REQUIRED_TEXT:
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise FileAssetError(f"الحقل {field} مطلوب.")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise FileAssetError("حجم الملف يجب أن يكون عدداً صحيحاً غير سالب.")
        if not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(self.sha256.lower()):
            raise FileAssetError("بصمة SHA-256 يجب أن تتكون من 64 خانة hexadecimal.")
        if self.validation_status not in {"unverified", "framing_checked", "validated", "rejected"}:
            raise FileAssetError("حالة التحقق غير معروفة.")
        try:
            payload = json.loads(self.metadata_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise FileAssetError("metadata_json ليس JSON صالحاً.") from exc
        if not isinstance(payload, dict):
            raise FileAssetError("metadata_json يجب أن يحتوي كائن JSON.")


def _asset_key(asset: FileAsset) -> str:
    """Stable identity for a model product/run/member/content combination."""
    identity = {
        "provider_id": asset.provider_id.casefold().strip(),
        "model_id": asset.model_id.casefold().strip(),
        "product_id": asset.product_id.casefold().strip(),
        "run_time_utc": asset.run_time_utc or "",
        "valid_time_utc": asset.valid_time_utc or "",
        "member_id": asset.member_id or "",
        "sha256": asset.sha256.lower(),
    }
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _source_key(source_uri: str) -> str:
    return hashlib.sha256(source_uri.encode("utf-8")).hexdigest()


class FileAssetCatalog:
    """Register immutable source assets in an explicitly selected DB profile."""

    def __init__(self, profile, secrets=None, *, timeout: int = 5):
        self.profile = profile
        self.secrets = secrets
        self.timeout = timeout
        profile.validate()

    def _connect(self):
        if not self.profile.enabled:
            raise FileAssetError("اتصال قاعدة البيانات معطّل.")
        if self.profile.backend == "sqlite":
            path = Path(self.profile.sqlite_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(path), timeout=self.timeout)
            connection.execute("PRAGMA foreign_keys = ON")
            return connection, "sqlite"
        if self.profile.backend == "postgresql":
            try:
                import psycopg
            except ImportError as exc:
                raise FileAssetError("موصل PostgreSQL psycopg غير مثبت.") from exc
            password = self.secrets.get_password(self.profile.credential_key) if self.secrets else None
            if not password:
                raise FileAssetError("كلمة مرور PostgreSQL غير موجودة في مخزن أسرار النظام.")
            options = {
                "host": self.profile.host, "port": self.profile.port,
                "dbname": self.profile.database, "user": self.profile.username,
                "password": password, "sslmode": self.profile.ssl_mode,
                "connect_timeout": self.timeout,
            }
            if self.profile.ssl_ca:
                options["sslrootcert"] = self.profile.ssl_ca
            return psycopg.connect(**options), "postgresql"
        if self.profile.backend in {"mysql", "mariadb"}:
            from .database_drivers import open_mysql_connection
            connection = open_mysql_connection(self.profile, self.secrets, timeout=self.timeout)
            connection.autocommit(False)
            return connection, "mysql"
        raise FileAssetError(f"محرك قاعدة البيانات غير مدعوم: {self.profile.backend}")

    def initialize_schema(self) -> None:
        """Explicit opt-in schema creation; never called by constructor or download flow."""
        connection, dialect = self._connect()
        try:
            cursor = connection.cursor()
            if dialect == "mysql":
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS file_assets (
                        asset_id CHAR(36) PRIMARY KEY,
                        asset_key CHAR(64) NOT NULL UNIQUE,
                        provider_id VARCHAR(128) NOT NULL,
                        model_id VARCHAR(128) NOT NULL,
                        product_id VARCHAR(128) NOT NULL,
                        local_path TEXT NOT NULL,
                        content_type VARCHAR(128) NOT NULL,
                        size_bytes BIGINT NOT NULL,
                        sha256 CHAR(64) NOT NULL,
                        run_time_utc VARCHAR(64),
                        valid_time_utc VARCHAR(64),
                        member_id VARCHAR(64),
                        validation_status VARCHAR(32) NOT NULL,
                        metadata_json LONGTEXT NOT NULL,
                        registered_at_utc VARCHAR(40) NOT NULL
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS file_asset_sources (
                        source_id CHAR(36) PRIMARY KEY,
                        asset_id CHAR(36) NOT NULL,
                        source_uri TEXT NOT NULL,
                        source_uri_sha256 CHAR(64) NOT NULL,
                        registered_at_utc VARCHAR(40) NOT NULL,
                        UNIQUE KEY uq_asset_source (asset_id, source_uri_sha256),
                        CONSTRAINT fk_asset_source FOREIGN KEY (asset_id)
                            REFERENCES file_assets(asset_id) ON DELETE CASCADE
                    )
                """)
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS file_assets (
                        asset_id TEXT PRIMARY KEY,
                        asset_key TEXT NOT NULL UNIQUE,
                        provider_id TEXT NOT NULL,
                        model_id TEXT NOT NULL,
                        product_id TEXT NOT NULL,
                        local_path TEXT NOT NULL,
                        content_type TEXT NOT NULL,
                        size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
                        sha256 TEXT NOT NULL,
                        run_time_utc TEXT,
                        valid_time_utc TEXT,
                        member_id TEXT,
                        validation_status TEXT NOT NULL,
                        metadata_json TEXT NOT NULL,
                        registered_at_utc TEXT NOT NULL
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS file_asset_sources (
                        source_id TEXT PRIMARY KEY,
                        asset_id TEXT NOT NULL REFERENCES file_assets(asset_id) ON DELETE CASCADE,
                        source_uri TEXT NOT NULL,
                        source_uri_sha256 TEXT NOT NULL,
                        registered_at_utc TEXT NOT NULL,
                        UNIQUE(asset_id, source_uri_sha256)
                    )
                """)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def register_asset(self, asset: FileAsset) -> dict[str, Any]:
        """Idempotently register metadata and preserve each distinct source URI."""
        asset.validate()
        from datetime import datetime, timezone

        asset_key = _asset_key(asset)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "webp:file-asset:" + asset_key))
        connection, dialect = self._connect()
        placeholder = "%s" if dialect in {"postgresql", "mysql"} else "?"
        try:
            cursor = connection.cursor()
            if dialect == "mysql":
                cursor.execute(
                    f"""INSERT INTO file_assets
                    (asset_id,asset_key,provider_id,model_id,product_id,local_path,content_type,
                     size_bytes,sha256,run_time_utc,valid_time_utc,member_id,validation_status,
                     metadata_json,registered_at_utc)
                    VALUES ({','.join([placeholder] * 15)})
                    ON DUPLICATE KEY UPDATE
                    local_path=VALUES(local_path), content_type=VALUES(content_type),
                    size_bytes=VALUES(size_bytes), validation_status=VALUES(validation_status),
                    metadata_json=VALUES(metadata_json)""",
                    (asset_id,asset_key,asset.provider_id,asset.model_id,asset.product_id,
                     asset.local_path,asset.content_type,asset.size_bytes,asset.sha256.lower(),
                     asset.run_time_utc,asset.valid_time_utc,asset.member_id,asset.validation_status,
                     asset.metadata_json,now),
                )
            else:
                cursor.execute(
                    f"""INSERT INTO file_assets
                    (asset_id,asset_key,provider_id,model_id,product_id,local_path,content_type,
                     size_bytes,sha256,run_time_utc,valid_time_utc,member_id,validation_status,
                     metadata_json,registered_at_utc)
                    VALUES ({','.join([placeholder] * 15)})
                    ON CONFLICT(asset_key) DO UPDATE SET
                    local_path=excluded.local_path, content_type=excluded.content_type,
                    size_bytes=excluded.size_bytes, validation_status=excluded.validation_status,
                    metadata_json=excluded.metadata_json""",
                    (asset_id,asset_key,asset.provider_id,asset.model_id,asset.product_id,
                     asset.local_path,asset.content_type,asset.size_bytes,asset.sha256.lower(),
                     asset.run_time_utc,asset.valid_time_utc,asset.member_id,asset.validation_status,
                     asset.metadata_json,now),
                )
            if asset.source_uri:
                source_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"webp:file-asset-source:{asset_id}:{_source_key(asset.source_uri)}"))
                cursor.execute(
                    f"""INSERT INTO file_asset_sources
                    (source_id,asset_id,source_uri,source_uri_sha256,registered_at_utc)
                    VALUES ({','.join([placeholder] * 5)})
                    ON CONFLICT(asset_id,source_uri_sha256) DO NOTHING"""
                    if dialect != "mysql" else
                    f"""INSERT INTO file_asset_sources
                    (source_id,asset_id,source_uri,source_uri_sha256,registered_at_utc)
                    VALUES ({','.join([placeholder] * 5)})
                    ON DUPLICATE KEY UPDATE source_uri=VALUES(source_uri)""",
                    (source_id,asset_id,asset.source_uri,_source_key(asset.source_uri),now),
                )
            connection.commit()
            return {"asset_id": asset_id, "asset_key": asset_key, "source_registered": bool(asset.source_uri)}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
