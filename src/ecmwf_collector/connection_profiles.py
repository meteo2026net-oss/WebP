"""Metadata-only profiles for multiple database connections.

Credentials are deliberately excluded from this module and its JSON files.
Use SecretStore with each profile's credential_key for password operations.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

DatabaseBackend = Literal["sqlite", "postgresql", "mysql", "mariadb"]
SUPPORTED_BACKENDS = frozenset({"sqlite", "postgresql", "mysql", "mariadb"})
SSL_MODES = frozenset({"disable", "prefer", "require", "verify-ca", "verify-full"})


class DatabaseProfileError(ValueError):
    """Invalid or inconsistent database profile."""


@dataclass(frozen=True)
class DatabaseProfile:
    profile_id: str
    name: str
    backend: DatabaseBackend
    database: str = ""
    host: str = ""
    port: int | None = None
    username: str = ""
    ssl_mode: str = "prefer"
    sqlite_path: str = ""
    enabled: bool = True
    credential_key: str = ""

    @classmethod
    def create(
        cls,
        name: str,
        backend: DatabaseBackend,
        *,
        database: str = "",
        host: str = "",
        port: int | None = None,
        username: str = "",
        ssl_mode: str = "prefer",
        sqlite_path: str = "",
        enabled: bool = True,
    ) -> "DatabaseProfile":
        profile_id = str(uuid.uuid4())
        return cls(
            profile_id=profile_id,
            name=name,
            backend=backend,
            database=database,
            host=host,
            port=port,
            username=username,
            ssl_mode=ssl_mode,
            sqlite_path=sqlite_path,
            enabled=enabled,
            credential_key=f"database-profile:{profile_id}",
        )

    def validate(self) -> None:
        if not self.profile_id.strip() or not self.name.strip():
            raise DatabaseProfileError("معرّف الاتصال واسمه مطلوبان.")
        if self.backend not in SUPPORTED_BACKENDS:
            raise DatabaseProfileError(f"نوع قاعدة البيانات غير مدعوم: {self.backend}")
        if self.ssl_mode not in SSL_MODES:
            raise DatabaseProfileError("وضع SSL غير صالح.")
        if self.backend == "sqlite":
            if not self.sqlite_path.strip():
                raise DatabaseProfileError("مسار ملف SQLite مطلوب.")
            if self.host or self.username or self.database or self.port is not None:
                raise DatabaseProfileError("إعدادات الخادم لا تنطبق على SQLite.")
        else:
            if not self.host.strip() or not self.database.strip() or not self.username.strip():
                raise DatabaseProfileError("المضيف واسم قاعدة البيانات واسم المستخدم مطلوبة.")
            if self.port is None or isinstance(self.port, bool) or not 1 <= self.port <= 65535:
                raise DatabaseProfileError("منفذ قاعدة البيانات يجب أن يكون بين 1 و65535.")
            if self.sqlite_path:
                raise DatabaseProfileError("مسار SQLite لا ينطبق على قواعد البيانات الخادمية.")
        if not self.credential_key.strip():
            raise DatabaseProfileError("مرجع بيانات الاعتماد مطلوب.")

    def to_metadata(self) -> dict:
        """Return serializable metadata; never includes a password or DSN."""
        self.validate()
        return asdict(self)

    @classmethod
    def from_metadata(cls, raw: dict) -> "DatabaseProfile":
        allowed = {
            "profile_id", "name", "backend", "database", "host", "port",
            "username", "ssl_mode", "sqlite_path", "enabled", "credential_key",
        }
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise DatabaseProfileError("ملف تعريف الاتصال يحتوي حقولاً غير معروفة.")
        profile = cls(**raw)
        profile.validate()
        return profile


class DatabaseProfileStore:
    """Atomic JSON registry containing connection metadata only."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def list_profiles(self) -> list[DatabaseProfile]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DatabaseProfileError("تعذّرت قراءة سجل اتصالات قواعد البيانات.") from exc
        if not isinstance(raw, list):
            raise DatabaseProfileError("صيغة سجل اتصالات قواعد البيانات غير صحيحة.")
        profiles = [DatabaseProfile.from_metadata(item) for item in raw]
        ids = [item.profile_id for item in profiles]
        if len(ids) != len(set(ids)):
            raise DatabaseProfileError("يوجد معرّف اتصال مكرر.")
        return profiles

    def get(self, profile_id: str) -> DatabaseProfile | None:
        return next((p for p in self.list_profiles() if p.profile_id == profile_id), None)

    def save(self, profile: DatabaseProfile) -> None:
        profile.validate()
        profiles = self.list_profiles()
        for index, current in enumerate(profiles):
            if current.profile_id == profile.profile_id:
                profiles[index] = profile
                break
        else:
            profiles.append(profile)
        self._write(profiles)

    def delete(self, profile_id: str) -> bool:
        profiles = self.list_profiles()
        remaining = [p for p in profiles if p.profile_id != profile_id]
        if len(remaining) == len(profiles):
            return False
        self._write(remaining)
        return True

    def _write(self, profiles: list[DatabaseProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="db-profiles-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump([p.to_metadata() for p in profiles], handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise
