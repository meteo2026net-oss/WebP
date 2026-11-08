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
            if (self.port is None or isinstance(self.port, bool) or not isinstance(self.port, int)
                    or not 1 <= self.port <= 65535):
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

    def set_password(self, profile: DatabaseProfile, secrets, password: str) -> bool:
        """Store a profile password in the OS credential vault, never in JSON."""
        profile.validate()
        if profile.backend == "sqlite":
            raise DatabaseProfileError("SQLite لا يحتاج كلمة مرور ضمن ملف الاتصال.")
        return bool(secrets.set_password(profile.credential_key, password))

    def get_password(self, profile: DatabaseProfile, secrets) -> str | None:
        profile.validate()
        if profile.backend == "sqlite":
            return None
        return secrets.get_password(profile.credential_key)

    def delete_with_secret(self, profile_id: str, secrets) -> bool:
        """Remove metadata first, then remove its OS-vault secret if one exists."""
        profile = self.get(profile_id)
        if profile is None:
            return False
        # Remove the OS-vault secret first. If that fails, keep the profile
        # metadata intact so the user can retry instead of leaving an orphaned
        # credential behind an already-deleted profile.
        if profile.backend != "sqlite" and not secrets.delete_password(profile.credential_key):
            return False
        return self.delete(profile_id)

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


def test_database_connection(profile: DatabaseProfile, secrets, timeout: int = 5) -> tuple[bool, str]:
    """Test only the selected database; never create databases or change user data."""
    import sqlite3

    profile.validate()
    if not profile.enabled:
        return False, "الاتصال معطّل."
    if profile.backend == "sqlite":
        path = Path(profile.sqlite_path).expanduser()
        if not path.is_file():
            return False, "ملف SQLite غير موجود؛ لم يتم إنشاء ملف جديد."
        connection = None
        try:
            connection = sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=timeout
            )
            connection.execute("SELECT 1").fetchone()
            return True, "اتصال SQLite سليم."
        except Exception as exc:
            return False, f"فشل اختبار SQLite ({type(exc).__name__})."
        finally:
            if connection is not None:
                connection.close()

    if profile.backend == "postgresql":
        try:
            import psycopg
        except ImportError:
            return False, "موصل PostgreSQL psycopg غير مثبت."
        password = secrets.get_password(profile.credential_key)
        if password is None:
            return False, "كلمة مرور هذا الاتصال غير موجودة في مخزن أسرار النظام."
        try:
            with psycopg.connect(
                host=profile.host,
                port=profile.port,
                dbname=profile.database,
                user=profile.username,
                password=password,
                sslmode=profile.ssl_mode,
                connect_timeout=timeout,
            ) as connection:
                connection.execute("SELECT 1")
            return True, "اتصال PostgreSQL سليم."
        except Exception as exc:
            return False, f"فشل اختبار PostgreSQL ({type(exc).__name__})."

    return False, f"اختبار {profile.backend} غير متاح بعد؛ لم تتم محاولة الاتصال."
