"""Optional PostgreSQL backend for the collector's download state."""
from __future__ import annotations

import csv
import threading
from pathlib import Path
from .state import COLUMNS, FileRecord, utc_now

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS public.files (
    remote_path TEXT PRIMARY KEY,
    remote_size BIGINT,
    local_path TEXT,
    status TEXT NOT NULL,
    local_size BIGINT,
    sha256 TEXT,
    detected_type TEXT,
    validation TEXT,
    downloaded_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL
)
"""
SELECT_COLUMNS = """remote_path,remote_size,local_path,status,local_size,sha256,
detected_type,validation,downloaded_at,attempts,last_error,updated_at"""


class PostgresStateStore:
    """Drop-in state store; connection is opened per operation to avoid thread sharing."""

    def __init__(self, dsn: str):
        if not dsn or not dsn.strip():
            raise ValueError("ECMWF_POSTGRES_DSN is empty.")
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("PostgreSQL mode requires psycopg[binary].") from exc
        self._psycopg = psycopg
        self._dsn = dsn
        self._lock = threading.RLock()
        with self._connect() as conn:
            # Never allow an environment-variable DSN or manual configuration to
            # silently bypass the restricted application account provisioner.
            role = conn.execute(
                """
                SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
                FROM pg_roles WHERE rolname = current_user
                """
            ).fetchone()
            if role is None:
                raise RuntimeError("تعذّر التحقق من صلاحيات حساب PostgreSQL الحالي.")
            if any(bool(flag) for flag in role):
                raise RuntimeError(
                    "رفض الاتصال: حساب PostgreSQL يجب ألا يملك صلاحيات مدير أو إنشاء قواعد/أدوار أو تجاوز RLS."
                )
            elevated_membership = conn.execute(
                """
                SELECT r.rolname
                FROM pg_roles AS r
                WHERE r.oid <> current_user::regrole::oid
                  AND (
                    r.rolsuper OR r.rolcreatedb OR r.rolcreaterole
                    OR r.rolreplication OR r.rolbypassrls
                    OR r.rolname IN (
                      'pg_read_all_data', 'pg_write_all_data',
                      'pg_execute_server_program', 'pg_read_server_files',
                      'pg_write_server_files', 'pg_monitor',
                      'pg_read_all_settings', 'pg_read_all_stats',
                      'pg_signal_backend'
                    )
                  )
                  AND pg_has_role(current_user, r.oid, 'MEMBER')
                LIMIT 1
                """
            ).fetchone()
            if elevated_membership:
                raise RuntimeError(
                    "رفض الاتصال: حساب PostgreSQL عضو في دور ذي صلاحيات مرتفعة."
                )
            table_access = conn.execute(
                """
                SELECT has_database_privilege(current_user, current_database(), 'CONNECT'),
                       has_schema_privilege(current_user, 'public', 'USAGE'),
                       to_regclass('public.files') IS NOT NULL,
                       has_table_privilege(current_user, 'public.files', 'SELECT'),
                       has_table_privilege(current_user, 'public.files', 'INSERT'),
                       has_table_privilege(current_user, 'public.files', 'UPDATE'),
                       has_table_privilege(current_user, 'public.files', 'DELETE')
                """
            ).fetchone()
            if table_access is None or not all(bool(flag) for flag in table_access):
                raise RuntimeError(
                    "رفض الاتصال: حساب التطبيق يفتقد CONNECT لقاعدة البيانات أو USAGE للمخطط "
                    "أو أن جدول public.files غير مهيأ أو صلاحيات القراءة والكتابة غير مكتملة. "
                    "أعد إعداد حساب التطبيق بأداة configure_postgres."
                )

    def _connect(self):
        return self._psycopg.connect(self._dsn, connect_timeout=8)

    def get(self, remote_path: str) -> FileRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT {SELECT_COLUMNS} FROM public.files WHERE remote_path=%s", (remote_path,)
            ).fetchone()
        return FileRecord(*row) if row else None

    def upsert(self, remote_path: str, **fields) -> None:
        bad = set(fields) - set(COLUMNS)
        if bad:
            raise ValueError(f"حقول غير معروفة: {bad}")
        now = utc_now()
        with self._lock, self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM public.files WHERE remote_path=%s", (remote_path,)).fetchone()
            if exists:
                if fields:
                    sets = ", ".join(f"{key}=%s" for key in fields)
                    conn.execute(
                        f"UPDATE public.files SET {sets}, updated_at=%s WHERE remote_path=%s",
                        (*fields.values(), now, remote_path),
                    )
                else:
                    conn.execute("UPDATE public.files SET updated_at=%s WHERE remote_path=%s", (now, remote_path))
            else:
                fields.setdefault("status", "pending")
                cols = ", ".join(("remote_path", *fields.keys(), "updated_at"))
                marks = ", ".join(["%s"] * (len(fields) + 2))
                conn.execute(
                    f"INSERT INTO public.files ({cols}) VALUES ({marks})",
                    (remote_path, *fields.values(), now),
                )

    def bump_attempts(self, remote_path: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE public.files SET attempts=attempts+1, updated_at=%s WHERE remote_path=%s",
                (utc_now(), remote_path),
            )

    def all_records(self) -> list[FileRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(f"SELECT {SELECT_COLUMNS} FROM public.files ORDER BY remote_path").fetchall()
        return [FileRecord(*row) for row in rows]

    def count(self) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM public.files").fetchone()[0])

    def import_records(self, records: list[FileRecord]) -> int:
        """Insert missing records and reject conflicting keys; never overwrite target data."""
        inserted = 0
        with self._lock, self._connect() as conn:
            for record in records:
                values = tuple(getattr(record, name) for name in (
                    "remote_path", "remote_size", "local_path", "status", "local_size", "sha256",
                    "detected_type", "validation", "downloaded_at", "attempts", "last_error", "updated_at"
                ))
                cur = conn.execute(
                    f"INSERT INTO public.files ({SELECT_COLUMNS}) VALUES ({', '.join(['%s'] * 12)}) "
                    "ON CONFLICT (remote_path) DO NOTHING",
                    values,
                )
                inserted += cur.rowcount
                existing = conn.execute(
                    f"SELECT {SELECT_COLUMNS} FROM public.files WHERE remote_path=%s", (record.remote_path,)
                ).fetchone()
                if existing != values:
                    raise RuntimeError(
                        f"Conflict for {record.remote_path!r}; target row differs. No source data was removed."
                    )
        return inserted

    def export_csv(self, path: Path) -> int:
        records = self.all_records()
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["remote_path", "status", "remote_size", "local_size", "sha256",
                             "detected_type", "validation", "downloaded_at_utc", "attempts",
                             "last_error", "local_path"])
            for row in records:
                writer.writerow([row.remote_path, row.status, row.remote_size, row.local_size, row.sha256,
                                 row.detected_type, row.validation, row.downloaded_at, row.attempts,
                                 row.last_error, row.local_path])
        return len(records)

    def close(self) -> None:
        return None
