"""Optional PostgreSQL backend for the collector's download state."""
from __future__ import annotations

import csv
import threading
from pathlib import Path
from .state import COLUMNS, FileRecord, utc_now

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS files (
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
            conn.execute(CREATE_TABLE)

    def _connect(self):
        return self._psycopg.connect(self._dsn, connect_timeout=8)

    def get(self, remote_path: str) -> FileRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT {SELECT_COLUMNS} FROM files WHERE remote_path=%s", (remote_path,)
            ).fetchone()
        return FileRecord(*row) if row else None

    def upsert(self, remote_path: str, **fields) -> None:
        bad = set(fields) - set(COLUMNS)
        if bad:
            raise ValueError(f"حقول غير معروفة: {bad}")
        now = utc_now()
        with self._lock, self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM files WHERE remote_path=%s", (remote_path,)).fetchone()
            if exists:
                if fields:
                    sets = ", ".join(f"{key}=%s" for key in fields)
                    conn.execute(
                        f"UPDATE files SET {sets}, updated_at=%s WHERE remote_path=%s",
                        (*fields.values(), now, remote_path),
                    )
                else:
                    conn.execute("UPDATE files SET updated_at=%s WHERE remote_path=%s", (now, remote_path))
            else:
                fields.setdefault("status", "pending")
                cols = ", ".join(("remote_path", *fields.keys(), "updated_at"))
                marks = ", ".join(["%s"] * (len(fields) + 2))
                conn.execute(
                    f"INSERT INTO files ({cols}) VALUES ({marks})",
                    (remote_path, *fields.values(), now),
                )

    def bump_attempts(self, remote_path: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE files SET attempts=attempts+1, updated_at=%s WHERE remote_path=%s",
                (utc_now(), remote_path),
            )

    def all_records(self) -> list[FileRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(f"SELECT {SELECT_COLUMNS} FROM files ORDER BY remote_path").fetchall()
        return [FileRecord(*row) for row in rows]

    def count(self) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])

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
                    f"INSERT INTO files ({SELECT_COLUMNS}) VALUES ({', '.join(['%s'] * 12)}) "
                    "ON CONFLICT (remote_path) DO NOTHING",
                    values,
                )
                inserted += cur.rowcount
                existing = conn.execute(
                    f"SELECT {SELECT_COLUMNS} FROM files WHERE remote_path=%s", (record.remote_path,)
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
