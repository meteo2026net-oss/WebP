"""إدارة ملفات تعريف اتصالات قواعد البيانات دون تخزين الأسرار في ملفات الإعدادات."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Backend = Literal["sqlite", "postgresql", "mysql", "mariadb"]
SUPPORTED_BACKENDS = {"sqlite", "postgresql", "mysql", "mariadb"}
SSL_MODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}


@dataclass(frozen=True)
class DatabaseProfile:
    id: str
    name: str
    backend: Backend
    database: str
    host: str = ""
    port: int | None = None
    username: str = ""
    ssl_mode: str = "prefer"
    enabled: bool = True

    def validate(self) -> None:
        if not self.id or not self.name.strip():
            raise ValueError("معرّف الاتصال واسمه مطلوبان.")
        if self.backend not in SUPPORTED_BACKENDS:
            raise ValueError("نوع قاعدة البيانات غير مدعوم.")
        if not self.database.strip():
            raise ValueError("اسم قاعدة البيانات أو مسار SQLite مطلوب.")
        if self.backend == "sqlite":
            if self.port is not None or self.host or self.username:
                raise ValueError("اتصال SQLite لا يحتاج مضيفاً أو منفذاً أو مستخدماً.")
        else:
            if not self.host.strip() or not self.username.strip():
                raise ValueError("المضيف واسم المستخدم مطلوبان.")
            if self.port is None or not 1 <= int(self.port) <= 65535:
                raise ValueError("منفذ قاعدة البيانات غير صالح.")
            if self.ssl_mode not in SSL_MODES:
                raise ValueError("وضع SSL غير صالح.")


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    message: str


class DatabaseProfileStore:
    """ملفات تعريف غير سرية؛ كلمات المرور تحفظ في SecretStore باستخدام معرّف ثابت."""

    def __init__(self, path: Path, secrets):
        self.path = Path(path)
        self.secrets = secrets
        self._profiles: dict[str, DatabaseProfile] = {}
        self.load()

    def load(self) -> list[DatabaseProfile]:
        if not self.path.exists():
            self._profiles = {}
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise ValueError("إصدار ملف اتصالات قواعد البيانات غير معروف.")
        profiles = {}
        for item in raw.get("profiles", []):
            profile = DatabaseProfile(**item)
            profile.validate()
            if profile.id in profiles:
                raise ValueError("معرّفات اتصالات مكررة.")
            profiles[profile.id] = profile
        self._profiles = profiles
        return self.list_profiles()

    def list_profiles(self) -> list[DatabaseProfile]:
        return sorted(self._profiles.values(), key=lambda p: (p.name.casefold(), p.id))

    def get(self, profile_id: str) -> DatabaseProfile:
        return self._profiles[profile_id]

    def save(self, profile: DatabaseProfile, password: str | None = None) -> None:
        profile.validate()
        if profile.id not in self._profiles and password is None and profile.backend != "sqlite":
            raise ValueError("كلمة المرور مطلوبة عند إنشاء اتصال جديد.")
        if password is not None:
            if not password:
                raise ValueError("كلمة المرور لا يمكن أن تكون فارغة.")
            if not self.secrets.set_password(self._secret_key(profile.id), password):
                raise RuntimeError("تعذّر حفظ كلمة المرور في مخزن أسرار نظام التشغيل.")
        self._profiles[profile.id] = profile
        self._write()

    def create(self, *, name: str, backend: Backend, database: str, host: str = "",
               port: int | None = None, username: str = "", ssl_mode: str = "prefer",
               enabled: bool = True, password: str | None = None) -> DatabaseProfile:
        profile = DatabaseProfile(
            id=uuid.uuid4().hex, name=name, backend=backend, database=database,
            host=host, port=port, username=username, ssl_mode=ssl_mode, enabled=enabled,
        )
        self.save(profile, password=password)
        return profile

    def set_enabled(self, profile_id: str, enabled: bool) -> DatabaseProfile:
        from dataclasses import replace
        profile = replace(self.get(profile_id), enabled=bool(enabled))
        self.save(profile)
        return profile

    def delete(self, profile_id: str, *, delete_secret: bool = True) -> None:
        self._profiles.pop(profile_id)
        self._write()
        if delete_secret:
            self.secrets.delete_password(self._secret_key(profile_id))

    def password_for(self, profile_id: str) -> str | None:
        return self.secrets.get_password(self._secret_key(profile_id))

    @staticmethod
    def _secret_key(profile_id: str) -> str:
        return f"database-profile:{profile_id}"

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "profiles": [asdict(p) for p in self.list_profiles()]}
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise


def test_database_connection(profile: DatabaseProfile, secrets) -> ConnectionTestResult:
    """اختبار اتصال قراءة فقط؛ لا ينشئ قواعد بيانات أو جداول ولا يغيّر المخطط."""
    profile.validate()
    if not profile.enabled:
        return ConnectionTestResult(False, "الاتصال معطّل.")
    try:
        if profile.backend == "sqlite":
            path = Path(profile.database).expanduser()
            if not path.is_file():
                return ConnectionTestResult(False, "ملف SQLite غير موجود؛ لم يتم إنشاؤه.")
            uri = path.resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=5) as connection:
                connection.execute("SELECT 1").fetchone()
            return ConnectionTestResult(True, "اتصال SQLite ناجح (قراءة فقط).")
        if profile.backend in {"mysql", "mariadb"}:
            return ConnectionTestResult(
                False, "موصل MySQL/MariaDB غير مضاف بعد؛ ملف التعريف محفوظ دون محاولة اتصال."
            )
        import psycopg
        from psycopg.conninfo import make_conninfo

        password = secrets.get_password(DatabaseProfileStore._secret_key(profile.id))
        if password is None:
            return ConnectionTestResult(False, "كلمة المرور غير موجودة في مخزن أسرار النظام.")
        dsn = make_conninfo(
            host=profile.host, port=profile.port, dbname=profile.database,
            user=profile.username, password=password, sslmode=profile.ssl_mode,
            connect_timeout=8,
        )
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute("SELECT 1").fetchone()
        return ConnectionTestResult(True, "اتصال PostgreSQL ناجح.")
    except Exception as exc:
        # لا نعيد نص الاستثناء لأن بعض برامج التشغيل قد تتضمن تفاصيل اتصال حساسة.
        return ConnectionTestResult(False, f"فشل الاتصال ({type(exc).__name__}).")
