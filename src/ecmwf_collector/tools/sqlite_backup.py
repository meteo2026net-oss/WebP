"""Consistent SQLite backup helper for the local collector state database."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path


def create_sqlite_backup(source: Path, backup: Path) -> None:
    """Create a consistent SQLite snapshot, including committed WAL transactions."""
    source = Path(source)
    backup = Path(backup)
    if not source.is_file():
        raise FileNotFoundError(source)
    backup.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == backup.resolve():
        raise ValueError("Source and backup paths must be different.")
    with closing(sqlite3.connect(source)) as source_db, closing(sqlite3.connect(backup)) as backup_db:
        source_db.backup(backup_db)
