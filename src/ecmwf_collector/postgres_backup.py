"""Secure custom-format PostgreSQL backups using the official pg_dump tools."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


def _connection_parts(dsn: str) -> dict[str, str]:
    if not dsn or not dsn.strip():
        raise ValueError("PostgreSQL connection string is empty.")
    try:
        from psycopg.conninfo import conninfo_to_dict
        values = conninfo_to_dict(dsn)
    except Exception as exc:
        raise ValueError("PostgreSQL connection string could not be parsed.") from exc
    return {str(key): str(value) for key, value in values.items() if value is not None}


def _tool(name: str, override: str | None = None) -> str:
    candidate = override or os.environ.get(f"ECMWF_{name.upper()}") or shutil.which(name)
    if not candidate:
        raise FileNotFoundError(
            f"{name} was not found. Install PostgreSQL client tools or set ECMWF_{name.upper()}."
        )
    path = Path(candidate)
    if path.is_file():
        return str(path)
    raise FileNotFoundError(f"PostgreSQL tool does not exist: {candidate}")


def _command_options(values: Mapping[str, str]) -> tuple[list[str], dict[str, str]]:
    from psycopg.conninfo import make_conninfo

    env = os.environ.copy()
    # Do not let an unrelated inherited password silently override this connection.
    env.pop("PGPASSWORD", None)
    connection = dict(values)
    password = connection.pop("password", None)
    if connection.get("sslpassword"):
        raise ValueError(
            "PostgreSQL SSL-key passwords are not supported by the desktop backup helper."
        )
    if password:
        # Keep credentials out of process command-line arguments.
        env["PGPASSWORD"] = password
    return ["--dbname", make_conninfo(**connection)], env

def create_postgres_backup(
    dsn: str, backup_dir: Path, keep: int = 30, *, pg_dump: str | None = None,
    pg_restore: str | None = None, timeout: int = 3600,
) -> Path:
    """Create and validate a pg_dump custom archive without exposing its password in argv."""
    if keep < 1:
        raise ValueError("At least one PostgreSQL backup must be retained.")
    values = _connection_parts(dsn)
    dump_exe = _tool("pg_dump", pg_dump)
    restore_exe = _tool("pg_restore", pg_restore)
    options, env = _command_options(values)
    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    database = values.get("dbname", "database")
    safe_database = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in database)[:40]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = directory / f"postgres-{safe_database}-{stamp}.dump"
    fd, temporary_name = tempfile.mkstemp(prefix=".postgres-backup-", suffix=".dump.tmp", dir=directory)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        dump_args = [dump_exe, "--no-password", "--format=custom", "--file", str(temporary), *options]
        result = subprocess.run(
            dump_args, env=env, capture_output=True, text=True, timeout=timeout, check=False
        )
        if result.returncode:
            detail = (result.stderr or result.stdout or "pg_dump failed").strip()
            raise RuntimeError(f"pg_dump failed ({result.returncode}): {detail[-2000:]}")
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError("pg_dump returned success but produced an empty archive.")
        verify = subprocess.run(
            [restore_exe, "--list", str(temporary)],
            env=env, capture_output=True, text=True, timeout=min(timeout, 300), check=False,
        )
        if verify.returncode:
            detail = (verify.stderr or verify.stdout or "pg_restore validation failed").strip()
            raise RuntimeError(f"PostgreSQL archive validation failed: {detail[-2000:]}")
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    candidates = sorted(
        (path for path in directory.glob(f"postgres-{safe_database}-*.dump") if path.is_file()),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for old in candidates[keep:]:
        old.unlink()
    return destination
