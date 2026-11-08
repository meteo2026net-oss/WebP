"""Safe, non-secret error used when a local download succeeded but catalog registration failed."""
from __future__ import annotations

from pathlib import Path


class CatalogRegistrationError(RuntimeError):
    """The downloaded asset remains on disk, but its metadata was not catalogued."""

    def __init__(self, file_path: Path, sidecar_path: Path, cause: Exception):
        self.file_path = Path(file_path)
        self.sidecar_path = Path(sidecar_path)
        self.cause_type = type(cause).__name__
        super().__init__(
            "تم حفظ الملف وبياناته الجانبية محلياً، لكن تعذّر تسجيله في قاعدة الكتالوج "
            f"({self.cause_type}). الملف: {self.file_path}"
        )
