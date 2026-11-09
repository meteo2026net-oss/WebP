"""Structural contract shared by the local and PostgreSQL file-state stores.

This deliberately describes only the operations used by download and GUI flows.
Backend-specific migration/backup capabilities remain explicit and are not hidden
behind this common contract.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .state import FileRecord


@runtime_checkable
class StateStoreProtocol(Protocol):
    """Minimal common interface for file download state persistence."""

    def get(self, remote_path: str) -> FileRecord | None:
        ...

    def upsert(self, remote_path: str, **fields: Any) -> None:
        ...

    def bump_attempts(self, remote_path: str) -> None:
        ...

    def count(self) -> int:
        ...

    def all_records(self) -> list[FileRecord]:
        ...

    def export_csv(self, path: Path) -> int:
        ...

    def close(self) -> None:
        ...
