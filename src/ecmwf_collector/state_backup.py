"""Verified, rotating SQLite snapshots for the desktop application's state database."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _snapshot(source: Path, destination: Path) -> None:
    source = Path(source)
    destination = Path(destination)
    if not source.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.stem}-", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    temp = Path(temp_name)
    try:
        with sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True) as src:
            with sqlite3.connect(temp) as dst:
                src.backup(dst)
                result = dst.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise sqlite3.DatabaseError(f"Backup integrity check failed: {result!r}")
                tables = {
                    row[0] for row in dst.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "files" not in tables:
                    raise sqlite3.DatabaseError("Backup does not contain the application files table.")
        os.replace(temp, destination)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def create_manual_backup(
    source: Path, backup_dir: Path, keep: int = 30
) -> Path:
    """Create a verified timestamped manual snapshot and rotate old manual snapshots."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = Path(backup_dir) / f"state-manual-{stamp}.db"
    _snapshot(Path(source), destination)
    _rotate(Path(backup_dir), "state-manual-", keep, destination)
    return destination


def ensure_daily_backup(
    source: Path, backup_dir: Path, keep: int = 30
) -> Path | None:
    """Create at most one verified automatic snapshot per UTC day."""
    source = Path(source)
    if not source.is_file():
        return None
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    destination = Path(backup_dir) / f"state-daily-{day}.db"
    if destination.is_file():
        try:
            _verify(destination)
            return destination
        except (OSError, sqlite3.DatabaseError):
            stamp = datetime.now(timezone.utc).strftime("%H%M%S")
            destination = Path(backup_dir) / f"state-daily-{day}-{stamp}.db"
    _snapshot(source, destination)
    _rotate(Path(backup_dir), "state-daily-", keep, destination)
    return destination


def _verify(path: Path) -> None:
    with sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True) as db:
        result = db.execute("PRAGMA integrity_check").fetchone()
        tables = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if not result or result[0] != "ok" or "files" not in tables:
            raise sqlite3.DatabaseError(f"Invalid application backup: {path}")


def _rotate(directory: Path, prefix: str, keep: int, newest: Path) -> None:
    if keep < 1:
        raise ValueError("At least one backup must be retained.")
    candidates = sorted(
        (p for p in directory.glob(f"{prefix}*.db") if p.is_file()),
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    )
    retained = 0
    for candidate in candidates:
        if candidate == newest or retained < keep:
            retained += 1
            continue
        candidate.unlink()
