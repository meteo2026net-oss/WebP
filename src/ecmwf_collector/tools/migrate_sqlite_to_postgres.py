"""Safely import the existing SQLite state into PostgreSQL without deleting SQLite."""
from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ecmwf_collector.state import StateStore
from ecmwf_collector.postgres_state import PostgresStateStore
from ecmwf_collector.secrets_store import SecretStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=Path("state/state.db"))
    parser.add_argument("--backup-dir", type=Path, default=Path("state/backups"))
    args = parser.parse_args()
    dsn = os.environ.get("ECMWF_POSTGRES_DSN", "").strip() or SecretStore().get_postgres_dsn()
    if not dsn:
        parser.error(
            "Configure a DSN with python -m ecmwf_collector.tools.configure_postgres "
            "or set ECMWF_POSTGRES_DSN."
        )
    source = args.sqlite.resolve()
    if not source.is_file():
        parser.error(f"SQLite database not found: {source}")
    args.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = args.backup_dir / f"state-{stamp}.db"
    # SQLite's online backup API captures a consistent snapshot, including committed
    # WAL content, even if the desktop app is still open.
    with sqlite3.connect(source) as source_db, sqlite3.connect(backup) as backup_db:
        source_db.backup(backup_db)
    sqlite = StateStore(source)
    postgres = None
    try:
        records = sqlite.all_records()
        postgres = PostgresStateStore(dsn)
        inserted = postgres.import_records(records)
        target_records = postgres.all_records()
        target_by_path = {row.remote_path: row for row in target_records}
        mismatches = [row.remote_path for row in records if target_by_path.get(row.remote_path) != row]
        if mismatches:
            raise RuntimeError(f"Verification failed for {len(mismatches)} records: {mismatches[:10]}")
        print(f"SQLite records: {len(records)}")
        print(f"New PostgreSQL records: {inserted}")
        print(f"Verified PostgreSQL records: {len(records)}")
        print(f"SQLite backup retained at: {backup}")
        return 0
    finally:
        sqlite.close()
        if postgres:
            postgres.close()


if __name__ == "__main__":
    raise SystemExit(main())
