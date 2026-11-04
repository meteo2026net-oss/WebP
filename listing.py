"""استعراض المجلدات والملفات على الخادم دون تنزيل."""
from __future__ import annotations

import ftplib
import logging
import posixpath
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from .connection import ConnectionSettings, FtpSession, open_session

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteEntry:
    name: str
    path: str
    is_dir: bool
    size: int | None = None
    modified: datetime | None = None  # UTC، أو None إن لم يوفرها الخادم


def parse_mlsd_time(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.split(".")[0], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


def parse_day_folder(name: str) -> datetime | None:
    """أسماء مجلدات الأيام. الخادم الفعلي يستخدم YYYYMMDD (تأكّد منه المستخدم)،
    أما الوثائق فتذكر dd-mm-yyyy 00:00، فندعم الصيغتين. التوقيت يُفترض UTC عرفًا (غير موثّق صراحة)."""
    for fmt in ("%Y%m%d", "%d-%m-%Y %H:%M", "%d-%m-%Y"):
        try:
            return datetime.strptime(name.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _to_int(v) -> int | None:
    try:
        n = int(v)
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


_LIST_RE = re.compile(
    r"^(?P<perm>[-dlbcps][rwxsStT-]{9})\s+\d+\s+\S+\s+\S+\s+(?P<size>\d+)\s+"
    r"\w{3}\s+\d{1,2}\s+[\d:]{4,5}\s+(?P<name>.+)$")


def _list_via_mlsd(ftp, path: str) -> list[RemoteEntry]:
    out = []
    for name, facts in ftp.mlsd(path, facts=["type", "size", "modify"]):
        t = facts.get("type", "").lower()
        if t in ("cdir", "pdir") or name in (".", ".."):
            continue
        out.append(RemoteEntry(name, posixpath.join(path, name), t == "dir",
                               _to_int(facts.get("size")) if t != "dir" else None,
                               parse_mlsd_time(facts.get("modify", ""))))
    return out


def _list_via_list(ftp, path: str) -> list[RemoteEntry]:
    lines: list[str] = []
    ftp.cwd(path)
    ftp.retrlines("LIST", lines.append)
    out = []
    for line in lines:
        m = _LIST_RE.match(line.strip())
        if not m:
            log.warning("سطر LIST غير مفهوم: %r", line[:120])
            continue
        name = m["name"].split(" -> ")[0]
        if name in (".", ".."):
            continue
        is_dir = m["perm"][0] == "d"
        # وقت التعديل في LIST بلا سنة ولا منطقة زمنية؛ لا نخمّنه.
        out.append(RemoteEntry(name, posixpath.join(path, name), is_dir,
                               None if is_dir else _to_int(m["size"]), None))
    return out


def list_directory(session: FtpSession, path: str = "/") -> list[RemoteEntry]:
    ftp = session.ftp
    try:
        entries = _list_via_mlsd(ftp, path)
    except ftplib.error_perm as exc:
        if not str(exc).startswith(("500", "501", "502", "504")):
            raise
        log.info("MLSD غير مدعوم؛ استخدام LIST")
        entries = _list_via_list(ftp, path)
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return entries


def sort_day_folders(entries: list[RemoteEntry]) -> list[RemoteEntry]:
    """الأحدث أولًا؛ المجلدات ذات الأسماء غير المفهومة في النهاية."""
    dated = [(parse_day_folder(e.name), e) for e in entries if e.is_dir]
    known = sorted([(d, e) for d, e in dated if d is not None], key=lambda x: x[0], reverse=True)
    unknown = [e for d, e in dated if d is None]
    return [e for _, e in known] + unknown


def filter_day_folders(entries: list[RemoteEntry], start: date | None, end: date | None) -> list[RemoteEntry]:
    """يصفّي المجلدات حسب التاريخ (شاملة). مجلد باسم غير مفهوم يُبقى ظاهرًا ولا يُخفى بصمت."""
    out = []
    for e in entries:
        d = parse_day_folder(e.name) if e.is_dir else None
        if d is None:
            out.append(e)
            continue
        if start and d.date() < start:
            continue
        if end and d.date() > end:
            continue
        out.append(e)
    return out


def browse(settings: ConnectionSettings, path: str = "/", **kwargs) -> list[RemoteEntry]:
    with open_session(settings, **kwargs) as session:
        return list_directory(session, path)


def human_size(n: int | None) -> str:
    if n is None:
        return "—"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"
