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


def asset_from_sidecar(sidecar_path: Path) -> FileAsset:
    """Build a trusted asset record from supported downloader sidecars.

    The sidecar is accepted only when its named file is a sibling, exists, and
    matches both the recorded byte count and SHA-256. Unknown source/model pairs
    are rejected instead of being guessed or routed to a default model.
    """
    sidecar_path = Path(sidecar_path).resolve()
    if not sidecar_path.is_file() or not sidecar_path.name.endswith(".source.json"):
        raise FileAssetError("ملف البيانات الجانبي .source.json غير موجود أو غير صالح.")
    try:
        metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FileAssetError("تعذرت قراءة بيانات المصدر الجانبية.") from exc
    if not isinstance(metadata, dict):
        raise FileAssetError("بيانات المصدر الجانبية يجب أن تكون كائن JSON.")

    source = str(metadata.get("source") or "").strip().casefold()
    model = str(metadata.get("model") or "").strip().casefold()
    integrity = str(metadata.get("integrity") or "").strip().casefold()
    if source == "noaa/ncep nomads":
        if "grib2 framing checked" not in integrity:
            raise FileAssetError("sidecar لا يثبت فحص إطار GRIB2؛ لا يمكن تسجيل الملف كملف مفحوص.")
    elif source in {"ecmwf_open_data", "cptec_inpe_eta"}:
        if integrity != "ok":
            raise FileAssetError("المصدر لم يسجل نتيجة فحص GRIB ناجحة.")
    if source == "ecmwf_open_data":
        model_ids = {"ifs": "ecmwf_ifs", "aifs-single": "ecmwf_aifs_single",
                     "aifs-ens": "ecmwf_aifs_ens"}
        if model not in model_ids:
            raise FileAssetError("نموذج ECMWF غير معروف؛ لن يتم تخمين هوية النموذج.")
        request = metadata.get("request") or {}
        if not isinstance(request, dict):
            raise FileAssetError("طلب ECMWF في sidecar غير صالح.")
        resolution = str(metadata.get("resolution") or "unknown")
        product_id = f"forecast_{str(request.get('type') or 'unknown')}_{resolution}"
        provider_id, model_id = "ecmwf_open_data", model_ids[model]
    elif source == "noaa/ncep nomads" and model in {"gfs", "gefs"}:
        provider_id = "noaa_nomads"
        model_id = f"noaa_{model}"
        resolution = str(metadata.get("resolution") or "unknown")
        product_id = f"{model}_{resolution}"
    elif source == "cptec_inpe_eta":
        domain = str(metadata.get("domain") or "").strip().casefold()
        if domain not in {"ams_08km", "ams_40km", "ons_40km", "rjsp_01km"}:
            raise FileAssetError("نطاق CPTEC ETA غير معروف.")
        provider_id, model_id, product_id = "cptec_inpe", "cptec_eta", f"eta_{domain}"
    else:
        raise FileAssetError("مصدر أو نموذج غير مدعوم في sidecar؛ لا يوجد توجيه تخميني.")

    filename = metadata.get("file") or metadata.get("file_name") or metadata.get("filename")
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        raise FileAssetError("اسم الملف في sidecar غير صالح.")
    asset_path = (sidecar_path.parent / filename).resolve()
    if asset_path.parent != sidecar_path.parent or not asset_path.is_file():
        raise FileAssetError("الملف المشار إليه غير موجود بجوار sidecar.")
    actual_size = asset_path.stat().st_size
    recorded_size = metadata.get("size_bytes")
    if isinstance(recorded_size, bool) or not isinstance(recorded_size, int) or recorded_size != actual_size:
        raise FileAssetError("حجم الملف لا يطابق الحجم المسجل في sidecar.")
    digest = hashlib.sha256()
    with asset_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    recorded_sha = str(metadata.get("sha256") or "").lower()
    if not _SHA256_RE.fullmatch(recorded_sha) or digest.hexdigest() != recorded_sha:
        raise FileAssetError("بصمة الملف لا تطابق SHA-256 المسجل في sidecar.")

    suffix = asset_path.suffix.casefold()
    content_types = {".grib": "application/x-grib", ".grb": "application/x-grib",
                     ".grib2": "application/x-grib2", ".grb2": "application/x-grib2",
                     ".nc": "application/x-netcdf", ".csv": "text/csv"}
    content_type = content_types.get(suffix)
    if content_type is None:
        raise FileAssetError("امتداد الملف غير مدعوم في كتالوج الأصول.")
    run_time = metadata.get("run")
    if not run_time and source == "cptec_inpe_eta":
        date_value = str(metadata.get("date") or "")
        cycle_value = str(metadata.get("cycle_utc") or "")
        try:
            from datetime import datetime
            datetime.strptime(date_value, "%Y%m%d")
            if cycle_value not in {"00", "06", "12", "18"}:
                raise ValueError
            run_time = (
                f"{date_value[:4]}-{date_value[4:6]}-{date_value[6:8]}"
                f"T{cycle_value}:00:00Z"
            )
        except ValueError as exc:
            raise FileAssetError("تاريخ أو دورة CPTEC في sidecar غير صالحين.") from exc
    if not run_time:
        run_time = metadata.get("cycle_utc")
    valid_time = metadata.get("valid_time") or metadata.get("returned_forecast_datetime")
    source_uri = metadata.get("source_url") or metadata.get("url")
    if source_uri is not None and not isinstance(source_uri, str):
        raise FileAssetError("رابط المصدر في sidecar غير صالح.")
    return FileAsset(
        provider_id=provider_id, model_id=model_id, product_id=product_id,
        local_path=str(asset_path), content_type=content_type, size_bytes=actual_size,
        sha256=recorded_sha, run_time_utc=str(run_time) if run_time else None,
        valid_time_utc=str(valid_time) if valid_time else None,
        member_id=str(metadata.get("member")) if metadata.get("member") else None,
        source_uri=source_uri, validation_status="framing_checked",
        metadata_json=json.dumps(metadata, ensure_ascii=False, sort_keys=True),
    )


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
                    CREATE TABLE IF NOT EXISTS webp_file_assets (
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
                    ) ENGINE=InnoDB
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS webp_file_asset_sources (
                        source_id CHAR(36) PRIMARY KEY,
                        asset_id CHAR(36) NOT NULL,
                        source_uri TEXT NOT NULL,
                        source_uri_sha256 CHAR(64) NOT NULL,
                        registered_at_utc VARCHAR(40) NOT NULL,
                        UNIQUE KEY uq_asset_source (asset_id, source_uri_sha256),
                        CONSTRAINT fk_webp_file_asset_sources_asset FOREIGN KEY (asset_id)
                            REFERENCES webp_file_assets(asset_id) ON DELETE CASCADE
                    ) ENGINE=InnoDB
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS webp_asset_outbox (
                        event_id CHAR(36) PRIMARY KEY,
                        asset_key CHAR(64) NOT NULL,
                        target_profile_id VARCHAR(128) NOT NULL,
                        status VARCHAR(16) NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        last_error TEXT,
                        created_at_utc VARCHAR(40) NOT NULL,
                        updated_at_utc VARCHAR(40) NOT NULL,
                        UNIQUE KEY uq_asset_outbox_target (asset_key, target_profile_id)
                    ) ENGINE=InnoDB
                """)
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS webp_file_assets (
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
                    CREATE TABLE IF NOT EXISTS webp_file_asset_sources (
                        source_id TEXT PRIMARY KEY,
                        asset_id TEXT NOT NULL REFERENCES webp_file_assets(asset_id) ON DELETE CASCADE,
                        source_uri TEXT NOT NULL,
                        source_uri_sha256 TEXT NOT NULL,
                        registered_at_utc TEXT NOT NULL,
                        UNIQUE(asset_id, source_uri_sha256)
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS webp_asset_outbox (
                        event_id TEXT PRIMARY KEY,
                        asset_key TEXT NOT NULL,
                        target_profile_id TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (status IN ('pending','processing','delivered','failed')),
                        attempts INTEGER NOT NULL DEFAULT 0,
                        last_error TEXT,
                        created_at_utc TEXT NOT NULL,
                        updated_at_utc TEXT NOT NULL,
                        UNIQUE(asset_key, target_profile_id)
                    )
                """)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def pending_outbox(self, *, target_profile_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise FileAssetError("حد دفعة Outbox يجب أن يكون بين 1 و1000.")
        connection, dialect = self._connect()
        placeholder = "%s" if dialect in {"postgresql", "mysql"} else "?"
        try:
            cursor = connection.cursor()
            sql = "SELECT event_id,asset_key,target_profile_id,attempts FROM webp_asset_outbox WHERE status IN ('pending','failed')"
            params: list[Any] = []
            if target_profile_id is not None:
                sql += f" AND target_profile_id={placeholder}"
                params.append(target_profile_id)
            sql += f" ORDER BY created_at_utc,event_id LIMIT {placeholder}"
            params.append(limit)
            cursor.execute(sql, tuple(params))
            return [{"event_id": row[0], "asset_key": row[1], "target_profile_id": row[2], "attempts": int(row[3])}
                    for row in cursor.fetchall()]
        finally:
            connection.close()

    def load_asset_variants(self, asset_key: str) -> list[FileAsset]:
        connection, dialect = self._connect()
        placeholder = "%s" if dialect in {"postgresql", "mysql"} else "?"
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"SELECT provider_id,model_id,product_id,local_path,content_type,size_bytes,sha256,run_time_utc,valid_time_utc,member_id,validation_status,metadata_json,asset_id FROM webp_file_assets WHERE asset_key={placeholder}",
                (asset_key,),
            )
            row = cursor.fetchone()
            if row is None:
                raise FileAssetError("أصل Outbox غير موجود في قاعدة المصدر.")
            cursor.execute(
                f"SELECT source_uri FROM webp_file_asset_sources WHERE asset_id={placeholder} ORDER BY source_uri_sha256",
                (row[12],),
            )
            uris = [item[0] for item in cursor.fetchall()] or [None]
            return [FileAsset(
                provider_id=row[0], model_id=row[1], product_id=row[2], local_path=row[3],
                content_type=row[4], size_bytes=int(row[5]), sha256=row[6],
                run_time_utc=row[7], valid_time_utc=row[8], member_id=row[9],
                source_uri=uri, validation_status=row[10], metadata_json=row[11],
            ) for uri in uris]
        finally:
            connection.close()

    def finish_outbox(self, event_id: str, *, delivered: bool, error: str | None = None) -> None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        connection, dialect = self._connect()
        placeholder = "%s" if dialect in {"postgresql", "mysql"} else "?"
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"UPDATE webp_asset_outbox SET status={placeholder}, attempts=attempts+1, last_error={placeholder}, updated_at_utc={placeholder} WHERE event_id={placeholder} AND status <> 'delivered'",
                ("delivered" if delivered else "failed", None if delivered else (error or "تعذر النقل")[:1000], now, event_id),
            )
            if getattr(cursor, "rowcount", 1) == 0:
                cursor.execute(
                    f"SELECT status FROM webp_asset_outbox WHERE event_id={placeholder}",
                    (event_id,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise FileAssetError("حدث Outbox غير موجود.")
                if existing[0] != "delivered":
                    raise FileAssetError("تعذر تحديث حالة حدث Outbox.")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def register_asset(self, asset: FileAsset, *, replica_profile_ids: tuple[str, ...] | list[str] = ()) -> dict[str, Any]:
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
                    f"""INSERT INTO webp_file_assets
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
                    f"""INSERT INTO webp_file_assets
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
                    f"""INSERT INTO webp_file_asset_sources
                    (source_id,asset_id,source_uri,source_uri_sha256,registered_at_utc)
                    VALUES ({','.join([placeholder] * 5)})
                    ON CONFLICT(asset_id,source_uri_sha256) DO NOTHING"""
                    if dialect != "mysql" else
                    f"""INSERT INTO webp_file_asset_sources
                    (source_id,asset_id,source_uri,source_uri_sha256,registered_at_utc)
                    VALUES ({','.join([placeholder] * 5)})
                    ON DUPLICATE KEY UPDATE source_uri=VALUES(source_uri)""",
                    (source_id,asset_id,asset.source_uri,_source_key(asset.source_uri),now),
                )
            targets = tuple(dict.fromkeys(replica_profile_ids))
            if any(not isinstance(target, str) or not target.strip() for target in targets):
                raise FileAssetError("معرّفات قواعد المزامنة غير صالحة.")
            if self.profile.profile_id in targets:
                raise FileAssetError("لا يمكن إضافة قاعدة المصدر نفسها كوجهة مزامنة.")
            for target_id in targets:
                event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"webp:asset-outbox:{asset_key}:{target_id}"))
                if dialect == "mysql":
                    cursor.execute("""
                        INSERT INTO webp_asset_outbox
                        (event_id,asset_key,target_profile_id,status,attempts,last_error,created_at_utc,updated_at_utc)
                        VALUES (%s,%s,%s,'pending',0,NULL,%s,%s)
                        ON DUPLICATE KEY UPDATE event_id=VALUES(event_id)
                    """, (event_id, asset_key, target_id, now, now))
                else:
                    marks = "%s,%s,%s,'pending',0,NULL,%s,%s" if dialect == "postgresql" else "?,?,?,'pending',0,NULL,?,?"
                    cursor.execute(f"""
                        INSERT INTO webp_asset_outbox
                        (event_id,asset_key,target_profile_id,status,attempts,last_error,created_at_utc,updated_at_utc)
                        VALUES ({marks})
                        ON CONFLICT(asset_key,target_profile_id) DO NOTHING
                    """, (event_id, asset_key, target_id, now, now))
            connection.commit()
            return {"asset_id": asset_id, "asset_key": asset_key,
                    "source_registered": bool(asset.source_uri), "outbox_enqueued": len(targets)}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
