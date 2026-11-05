"""Safe selection and recovery for the local application state backend."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .postgres_state import PostgresStateStore
from .state import StateStore

SQLITE_ONCE = "sqlite_once"
REMOVE_SAVED_AND_USE_SQLITE = "remove_saved_and_use_sqlite"
EXIT = "exit"


def open_state_store(
    data_root: Path,
    secrets,
    postgres_dsn: str | None,
    recover: Callable[[Exception, bool], str],
):
    """Open PostgreSQL with an explicit, non-destructive SQLite fallback.

    The recovery callback receives the connection error and whether the DSN
    came from the environment. The SQLite database is never deleted here.
    """
    if not postgres_dsn:
        return StateStore(Path(data_root) / "state" / "state.db")

    try:
        return PostgresStateStore(postgres_dsn)
    except Exception as exc:
        environment_dsn = bool(os.environ.get("ECMWF_POSTGRES_DSN", "").strip())
        choice = recover(exc, environment_dsn)
        if choice == SQLITE_ONCE:
            return StateStore(Path(data_root) / "state" / "state.db")
        if choice == REMOVE_SAVED_AND_USE_SQLITE:
            if environment_dsn:
                raise ValueError(
                    "Cannot remove a PostgreSQL DSN supplied by the ECMWF_POSTGRES_DSN environment variable."
                ) from exc
            if not secrets.delete_postgres_dsn():
                raise RuntimeError(
                    "Could not remove the saved PostgreSQL connection from the OS credential vault."
                ) from exc
            return StateStore(Path(data_root) / "state" / "state.db")
        if choice == EXIT:
            return None
        raise ValueError(f"Unknown PostgreSQL recovery choice: {choice!r}") from exc
