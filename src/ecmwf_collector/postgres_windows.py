"""Read-only diagnostics for locally installed PostgreSQL server and client tools."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


_TOOL_NAMES = ("postgres", "pg_ctl", "initdb", "pg_dump", "pg_restore")


def _install_roots() -> list[Path]:
    roots = {
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles(x86)"),
    }
    return [Path(value) / "PostgreSQL" for value in sorted(roots) if value]


def _find_binary(name: str) -> str | None:
    executable = f"{name}.exe" if os.name == "nt" else name
    located = shutil.which(executable)
    if located:
        return located
    for root in _install_roots():
        try:
            versions = sorted(
                (item for item in root.iterdir() if item.is_dir()),
                key=lambda item: tuple(
                    int(part) if part.isdigit() else -1
                    for part in item.name.split(".")
                ),
                reverse=True,
            )
        except OSError:
            continue
        for version in versions:
            candidate = version / "bin" / executable
            if candidate.is_file():
                return str(candidate)
    return None


def _windows_services() -> list[dict[str, str]]:
    if os.name != "nt":
        return []
    try:
        result = subprocess.run(
            ["sc.exe", "query", "state=", "all"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode:
        return []
    names = re.findall(
        r"^\s*SERVICE_NAME:\s*(postgresql[^\r\n]*)",
        result.stdout or "", flags=re.IGNORECASE | re.MULTILINE,
    )
    services: list[dict[str, str]] = []
    for name in sorted(set(names), key=str.casefold):
        try:
            detail = subprocess.run(
                ["sc.exe", "query", name],
                capture_output=True, text=True, timeout=10, check=False,
            )
            output = detail.stdout or ""
            match = re.search(r"STATE\s*:\s*\d+\s+(\w+)", output, re.IGNORECASE)
            services.append({
                "name": name,
                "state": match.group(1).upper() if match else "UNKNOWN",
            })
        except (OSError, subprocess.TimeoutExpired):
            services.append({"name": name, "state": "UNKNOWN"})
    return services


def diagnose_postgres_installation() -> dict[str, Any]:
    """Return local installation facts only; never starts, stops, or changes a service."""
    tools = {name: _find_binary(name) for name in _TOOL_NAMES}
    services = _windows_services()
    return {
        "platform": os.name,
        "server_binary_found": tools["postgres"] is not None,
        "client_tools_found": all(tools[name] for name in ("pg_dump", "pg_restore")),
        "tools": tools,
        "services": services,
        "service_running": any(item["state"] == "RUNNING" for item in services),
        "server_installation_detected": tools["postgres"] is not None or bool(services),
        "read_only": True,
    }
