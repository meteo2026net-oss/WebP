"""Secure custom-format PostgreSQL backups using the official pg_dump tools."""
from __future__ import annotations

import hashlib
import hmac
import re
import json
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


def _windows_tool_candidates(name: str) -> list[Path]:
    """Find EDB client tools in standard Windows install folders, without a disk scan."""
    executable = f"{name}.exe"
    roots = {
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles(x86)"),
    }
    candidates: list[Path] = []
    for root in sorted(value for value in roots if value):
        install_root = Path(root) / "PostgreSQL"
        try:
            versions = sorted(
                (path for path in install_root.iterdir() if path.is_dir()),
                key=lambda path: tuple(int(part) if part.isdigit() else -1
                                       for part in path.name.split(".")),
                reverse=True,
            )
        except OSError:
            continue
        candidates.extend(version / "bin" / executable for version in versions)
    return candidates


def _tool(name: str, override: str | None = None) -> str:
    configured = override or os.environ.get(f"ECMWF_{name.upper()}")
    if configured:
        path = Path(configured)
        if path.is_file():
            return str(path)
        raise FileNotFoundError(f"PostgreSQL tool does not exist: {configured}")

    located = shutil.which(name)
    if located:
        return located

    # PostgreSQL's Windows installer normally uses Program Files/PostgreSQL/<version>/bin.
    for path in _windows_tool_candidates(name):
        if path.is_file():
            return str(path)

    raise FileNotFoundError(
        f"{name} was not found. Install PostgreSQL client tools, add their bin "
        f"folder to PATH, or set ECMWF_{name.upper()} to the executable path."
    )


def _tool_major_version(executable: str, *, timeout: int = 10) -> int:
    result = subprocess.run(
        [executable, "--version"], capture_output=True, text=True,
        timeout=timeout, check=False,
    )
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode or "PostgreSQL" not in output:
        raise RuntimeError(f"Could not determine PostgreSQL tool version: {executable}")
    match = re.search(r"PostgreSQL\)\s+(\d+)", output)
    if not match:
        raise RuntimeError(f"Unrecognized PostgreSQL tool version: {output[:200]}")
    return int(match.group(1))


def _validate_tool_pair(pg_dump: str, pg_restore: str) -> None:
    dump_major = _tool_major_version(pg_dump)
    restore_major = _tool_major_version(pg_restore)
    if dump_major != restore_major:
        raise RuntimeError(
            "pg_dump and pg_restore must use the same PostgreSQL major version "
            f"(found {dump_major} and {restore_major})."
        )


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


def _sha256_file(path: Path) -> str:
    """Hash large archives incrementally instead of loading them into RAM."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    _validate_tool_pair(dump_exe, restore_exe)
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
        digest = _sha256_file(temporary)
        metadata = {
            "format": "postgresql-custom",
            "database": database,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "size_bytes": temporary.stat().st_size,
            "sha256": digest,
        }
        manifest_tmp = destination.with_suffix(destination.suffix + ".json.tmp")
        manifest_path = destination.with_suffix(destination.suffix + ".json")
        try:
            manifest_tmp.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, destination)
            os.replace(manifest_tmp, manifest_path)
        except BaseException:
            destination.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            raise
        finally:
            manifest_tmp.unlink(missing_ok=True)
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
        old.with_suffix(old.suffix + ".json").unlink(missing_ok=True)
    return destination


def validate_postgres_backup_manifest(archive: Path) -> dict[str, object]:
    """Verify sidecar metadata and SHA-256 before a backup is copied or restored."""
    archive = Path(archive)
    manifest_path = archive.with_suffix(archive.suffix + ".json")
    try:
        metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("PostgreSQL backup manifest is missing or invalid.") from exc
    if not isinstance(metadata, dict):
        raise ValueError("PostgreSQL backup manifest must contain a JSON object.")
    if metadata.get("format") != "postgresql-custom":
        raise ValueError("Unsupported PostgreSQL backup manifest format.")
    expected_size = metadata.get("size_bytes")
    expected_digest = metadata.get("sha256")
    database = metadata.get("database")
    if not isinstance(database, str) or not database.strip():
        raise ValueError("PostgreSQL backup manifest has no valid database name.")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 1:
        raise ValueError("PostgreSQL backup manifest has an invalid archive size.")
    if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise ValueError("PostgreSQL backup manifest has an invalid SHA-256 digest.")
    if not archive.is_file() or archive.stat().st_size != expected_size:
        raise ValueError("PostgreSQL backup size does not match its manifest.")
    digest = _sha256_file(archive)
    if not hmac.compare_digest(digest, expected_digest):
        raise ValueError("PostgreSQL backup checksum does not match its manifest.")
    return metadata
