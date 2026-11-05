"""سجل حالة الملفات في SQLite (state/state.db): الحالة والحجم والتاريخ وبصمة SHA-256."""
from __future__ import annotations

import csv
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = ("remote_size", "local_path", "status", "local_size", "sha256", "detected_type",
           "validation", "downloaded_at", "attempts", "last_error")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class FileRecord:
    remote_path: str
    remote_size: int | None
    local_path: str | None
    status: str
    local_size: int | None
    sha256: str | None
    detected_type: str | None
    validation: str | None
    downloaded_at: str | None
    attempts: int
    last_error: str | None
    updated_at: str


class StateStore:
    def __init__(self, path: Path):
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("""CREATE TABLE IF NOT EXISTS files (
            remote_path TEXT PRIMARY KEY, remote_size INTEGER, local_path TEXT, status TEXT NOT NULL,
            local_size INTEGER, sha256 TEXT, detected_type TEXT, validation TEXT, downloaded_at TEXT,
            attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, updated_at TEXT NOT NULL)""")
        self._db.commit()

    def get(self, remote_path: str) -> FileRecord | None:
        with self._lock:
            row = self._db.execute("SELECT remote_path,remote_size,local_path,status,local_size,sha256,"
                                   "detected_type,validation,downloaded_at,attempts,last_error,updated_at "
                                   "FROM files WHERE remote_path=?", (remote_path,)).fetchone()
        return FileRecord(*row) if row else None

    def upsert(self, remote_path: str, **fields) -> None:
        bad = set(fields) - set(COLUMNS)
        if bad:
            raise ValueError(f"حقول غير معروفة: {bad}")
        with self._lock:
            exists = self._db.execute("SELECT 1 FROM files WHERE remote_path=?", (remote_path,)).fetchone()
            now = utc_now()
            if exists:
                if fields:
                    sets = ", ".join(f"{k}=?" for k in fields)
                    self._db.execute(f"UPDATE files SET {sets}, updated_at=? WHERE remote_path=?",
                                     (*fields.values(), now, remote_path))
                else:
                    self._db.execute("UPDATE files SET updated_at=? WHERE remote_path=?", (now, remote_path))
            else:
                fields.setdefault("status", "pending")
                cols = ", ".join(("remote_path", *fields, "updated_at"))
                marks = ", ".join("?" * (len(fields) + 2))
                self._db.execute(f"INSERT INTO files ({cols}) VALUES ({marks})", (remote_path, *fields.values(), now))
            self._db.commit()

    def bump_attempts(self, remote_path: str) -> None:
        with self._lock:
            self._db.execute("UPDATE files SET attempts=attempts+1, updated_at=? WHERE remote_path=?",
                             (utc_now(), remote_path))
            self._db.commit()

    def count(self) -> int:
        """Return the number of tracked remote files."""
        with self._lock:
            row = self._db.execute("SELECT COUNT(*) FROM files").fetchone()
        return int(row[0])

    def all_records(self) -> list[FileRecord]:
        with self._lock:
            rows = self._db.execute("SELECT remote_path,remote_size,local_path,status,local_size,sha256,"
                                    "detected_type,validation,downloaded_at,attempts,last_error,updated_at "
                                    "FROM files ORDER BY remote_path").fetchall()
        return [FileRecord(*r) for r in rows]

    def export_csv(self, path: Path) -> int:
        recs = self.all_records()
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["remote_path", "status", "remote_size", "local_size", "sha256", "detected_type",
                        "validation", "downloaded_at_utc", "attempts", "last_error", "local_path"])
            for r in recs:
                w.writerow([r.remote_path, r.status, r.remote_size, r.local_size, r.sha256, r.detected_type,
                            r.validation, r.downloaded_at, r.attempts, r.last_error, r.local_path])
        return len(recs)

    def close(self) -> None:
        with self._lock:
            self._db.close()
