"""قراءة مؤشرات صحة قواعد البيانات وسجل الملفات دون تعديل البيانات.

الأرقام هنا تخص جدول تتبع التنزيلات (public.files / files)، ولا تمثل عدد
ملفات CSV الفعلية على القرص أو عدد سجلات الطقس داخل ملفات GRIB/CSV.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .connection_profiles import DatabaseProfile


@dataclass(frozen=True)
class DatabaseHealth:
    profile_id: str
    profile_name: str
    backend: str
    connected: bool
    tracking_table_available: bool
    tracked_files: int | None = None
    completed_files: int | None = None
    failed_files: int | None = None
    remote_bytes: int | None = None
    local_bytes: int | None = None
    database_bytes: int | None = None
    latest_update: str | None = None
    message: str = ""


def inspect_database(profile: DatabaseProfile, secrets, timeout: int = 5) -> DatabaseHealth:
    """Collect read-only tracking metadata and physical size for one enabled DB profile."""
    profile.validate()
    base = dict(
        profile_id=profile.profile_id,
        profile_name=profile.name,
        backend=profile.backend,
    )
    if not profile.enabled:
        return DatabaseHealth(**base, connected=False, tracking_table_available=False,
                              message="الاتصال معطّل.")
    if profile.backend == "sqlite":
        path = Path(profile.sqlite_path).expanduser()
        if not path.is_file():
            return DatabaseHealth(**base, connected=False, tracking_table_available=False,
                                  message="ملف SQLite غير موجود؛ لم يتم إنشاؤه.")
        connection = None
        try:
            connection = sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=timeout
            )
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='files'"
            ).fetchone()
            wal_path = path.with_name(path.name + "-wal")
            database_bytes = path.stat().st_size + (wal_path.stat().st_size if wal_path.is_file() else 0)
            if not table:
                return DatabaseHealth(**base, connected=True, tracking_table_available=False,
                                      database_bytes=database_bytes,
                                      message="الاتصال سليم، لكن جدول تتبع الملفات غير موجود.")
            row = connection.execute(
                """SELECT COUNT(*),
                          SUM(CASE WHEN status='complete' THEN 1 ELSE 0 END),
                          SUM(CASE WHEN status IN ('failed','invalid') THEN 1 ELSE 0 END),
                          COALESCE(SUM(remote_size), 0),
                          COALESCE(SUM(local_size), 0),
                          MAX(updated_at)
                   FROM files"""
            ).fetchone()
            return DatabaseHealth(
                **base, connected=True, tracking_table_available=True,
                tracked_files=int(row[0] or 0), completed_files=int(row[1] or 0),
                failed_files=int(row[2] or 0), remote_bytes=int(row[3] or 0),
                local_bytes=int(row[4] or 0), database_bytes=database_bytes,
                latest_update=row[5], message="تم فحص سجل التتبع بوضع القراءة فقط.",
            )
        except Exception as exc:
            return DatabaseHealth(**base, connected=False, tracking_table_available=False,
                                  message=f"تعذّر فحص SQLite ({type(exc).__name__}).")
        finally:
            if connection is not None:
                connection.close()

    if profile.backend == "postgresql":
        try:
            import psycopg
        except ImportError:
            return DatabaseHealth(**base, connected=False, tracking_table_available=False,
                                  message="موصل PostgreSQL psycopg غير مثبت.")
        password = secrets.get_password(profile.credential_key) if secrets else None
        if not password:
            return DatabaseHealth(**base, connected=False, tracking_table_available=False,
                                  message="بيانات اعتماد الاتصال غير متاحة في مخزن أسرار النظام.")
        try:
            with psycopg.connect(
                host=profile.host, port=profile.port, dbname=profile.database,
                user=profile.username, password=password, sslmode=profile.ssl_mode,
                connect_timeout=timeout, options="-c default_transaction_read_only=on",
                **({"sslrootcert": profile.ssl_ca} if profile.ssl_ca else {}),
            ) as connection:
                database_bytes = int(connection.execute(
                    "SELECT pg_database_size(current_database())"
                ).fetchone()[0])
                table = connection.execute("SELECT to_regclass('public.files')").fetchone()[0]
                if table is None:
                    return DatabaseHealth(**base, connected=True, tracking_table_available=False,
                                          database_bytes=database_bytes,
                                          message="الاتصال سليم، لكن جدول public.files غير موجود.")
                row = connection.execute(
                    """SELECT COUNT(*),
                              COUNT(*) FILTER (WHERE status='complete'),
                              COUNT(*) FILTER (WHERE status IN ('failed','invalid')),
                              COALESCE(SUM(remote_size), 0),
                              COALESCE(SUM(local_size), 0),
                              MAX(updated_at)
                       FROM public.files"""
                ).fetchone()
            return DatabaseHealth(
                **base, connected=True, tracking_table_available=True,
                tracked_files=int(row[0] or 0), completed_files=int(row[1] or 0),
                failed_files=int(row[2] or 0), remote_bytes=int(row[3] or 0),
                local_bytes=int(row[4] or 0), database_bytes=database_bytes,
                latest_update=row[5].isoformat() if hasattr(row[5], "isoformat") else row[5],
                message="تم فحص سجل التتبع بوضع القراءة فقط.",
            )
        except Exception as exc:
            return DatabaseHealth(**base, connected=False, tracking_table_available=False,
                                  message=f"تعذّر فحص PostgreSQL ({type(exc).__name__}).")

    if profile.backend in {"mysql", "mariadb"}:
        connection = None
        try:
            from .database_drivers import open_mysql_connection
            connection = open_mysql_connection(profile, secrets, timeout=timeout)
            from .database_drivers import assert_mysql_application_role
            assert_mysql_application_role(connection, profile.database)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COALESCE(SUM(data_length + index_length), 0) "
                    "FROM information_schema.tables WHERE table_schema=%s",
                    (profile.database,),
                )
                database_bytes = int(cursor.fetchone()[0] or 0)
                cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema=%s AND table_name='files'",
                    (profile.database,),
                )
                table_exists = bool(cursor.fetchone()[0])
                if not table_exists:
                    return DatabaseHealth(
                        **base, connected=True, tracking_table_available=False,
                        database_bytes=database_bytes,
                        message="الاتصال سليم، لكن جدول تتبع الملفات غير موجود.",
                    )
                cursor.execute(
                    """SELECT COUNT(*),
                              SUM(CASE WHEN status='complete' THEN 1 ELSE 0 END),
                              SUM(CASE WHEN status IN ('failed','invalid') THEN 1 ELSE 0 END),
                              COALESCE(SUM(remote_size), 0),
                              COALESCE(SUM(local_size), 0),
                              MAX(updated_at)
                       FROM files"""
                )
                row = cursor.fetchone()
            return DatabaseHealth(
                **base, connected=True, tracking_table_available=True,
                tracked_files=int(row[0] or 0), completed_files=int(row[1] or 0),
                failed_files=int(row[2] or 0), remote_bytes=int(row[3] or 0),
                local_bytes=int(row[4] or 0), database_bytes=database_bytes,
                latest_update=row[5].isoformat() if hasattr(row[5], "isoformat") else row[5],
                message="تم فحص سجل التتبع بوضع القراءة فقط.",
            )
        except ImportError:
            return DatabaseHealth(**base, connected=False, tracking_table_available=False,
                                  message="موصل MySQL/MariaDB PyMySQL غير مثبت.")
        except Exception as exc:
            return DatabaseHealth(**base, connected=False, tracking_table_available=False,
                                  message=f"تعذّر فحص {profile.backend} ({type(exc).__name__}).")
        finally:
            if connection is not None:
                connection.close()

    return DatabaseHealth(**base, connected=False, tracking_table_available=False,
                          message=f"فحص {profile.backend} غير متاح حتى إضافة موصله.")
