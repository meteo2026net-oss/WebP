"""سجل أخطاء مقروء مع حجب أي كلمة مرور من المخرجات."""
from __future__ import annotations

import logging
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SECRETS: set[str] = set()
_PATTERN = re.compile(r"(?i)\b(PASS|password|passwd|pwd)\b(\s*[=:]?\s*)\S+")
MASK = "********"


def register_secret(value: str | None) -> None:
    if value and len(value) >= 3:
        _SECRETS.add(value)


def clear_secrets() -> None:
    _SECRETS.clear()


def redact(text: str) -> str:
    for secret in sorted(_SECRETS, key=len, reverse=True):
        text = text.replace(secret, MASK)
    return _PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)


class RedactingFormatter(logging.Formatter):
    converter = time.gmtime  # توقيت UTC

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(log_dir: Path, level: int = logging.INFO) -> Path:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "collector.log"
    handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(RedactingFormatter("%(asctime)s UTC | %(levelname)-7s | %(name)s | %(message)s"))
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, RotatingFileHandler):
            root.removeHandler(h)
            h.close()
    root.addHandler(handler)
    root.setLevel(level)
    return log_file
