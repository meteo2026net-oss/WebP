"""التخطيط والتنزيل: ملف مؤقت .part، استكمال بـ REST، SHA-256، تحقق ثم إعادة تسمية ذرّية.

- الملفات الأصلية تُحفظ كما هي (بنفس الاسم وبلا امتداد) في downloads/YYYY-MM-DD/original_files/.
- الملف الكامل لا يُعاد تنزيله إلا إذا تغيّر حجمه على الخادم.
- الإيقاف المؤقت/الآمن يقطع النقل عند حدّ الكتلة ويُبقي .part للاستكمال؛ لا يُنتج ملفًا نهائيًا ناقصًا.
- ملف يفشل تحقق بنيته يُحفظ باسم NAME.invalid ولا يُعدّ ناجحًا.
"""
from __future__ import annotations

import errno
import ftplib
import hashlib
import logging
import os
import posixpath
import shutil
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from .connection import (AuthenticationError, ConnectionSettings, FtpError, NetworkError,
                         default_ftp_factory, open_session)
from .fileinspect import inspect_file
from .listing import (filter_day_folders, human_size, list_directory, parse_day_folder,
                      sort_day_folders)
from .naming import ProductFile, parse_product_name
from .state import StateStore, utc_now

log = logging.getLogger(__name__)
ALL_KINDS = frozenset({"AN", "FM", "FP", "FS"})
ALL_CYCLES = frozenset({"00", "06", "12", "18"})


@dataclass(frozen=True)
class Filters:
    kinds: frozenset = ALL_KINDS
    cycles: frozenset = ALL_CYCLES
    include_unknown: bool = True  # أسماء لا نفهمها تبقى ضمن الخطة بدل أن تُهمل بصمت

    def accepts(self, info: ProductFile | None) -> bool:
        if info is None:
            return self.include_unknown
        return info.kind in self.kinds and f"{info.base.hour:02d}" in self.cycles


@dataclass
class PlanItem:
    folder: str
    name: str
    remote_path: str
    size: int | None
    info: ProductFile | None
    local_path: Path
    action: str  # new | resume | changed | skip

    @property
    def part_path(self) -> Path:
        return self.local_path.with_name(self.local_path.name + ".part")


@dataclass
class Plan:
    items: list[PlanItem] = field(default_factory=list)

    @property
    def to_download(self) -> list[PlanItem]:
        return [i for i in self.items if i.action != "skip"]

    @property
    def bytes_remaining(self) -> int:
        total = 0
        for i in self.to_download:
            part = i.part_path.stat().st_size if i.action == "resume" and i.part_path.exists() else 0
            total += max((i.size or 0) - part, 0)
        return total

    def summary_ar(self) -> str:
        c = {a: sum(1 for i in self.items if i.action == a) for a in ("new", "resume", "changed", "skip")}
        folders = sorted({i.folder for i in self.items})
        return (f"المجلدات: {len(folders)} | ملفات مطابقة للتصفية: {len(self.items)}\n"
                f"جديدة: {c['new']} | قابلة للاستكمال: {c['resume']} | تغيّر حجمها: {c['changed']} | "
                f"مكتملة سابقًا (تُتخطى): {c['skip']}\n"
                f"الحجم المطلوب تنزيله: {human_size(self.bytes_remaining)}")


def _safe_name(name: str) -> bool:
    return bool(name) and name not in (".", "..") and not any(c in name for c in '/\\:*?"<>|\x00')


def local_file_path(download_root: Path, folder: str, name: str) -> Path:
    d = parse_day_folder(folder)
    day = d.strftime("%Y-%m-%d") if d else "unknown_" + "".join(c if c.isalnum() or c in "-_" else "_" for c in folder)
    return Path(download_root) / day / "original_files" / name


def _decide(rec, local: Path, size: int | None) -> str:
    part = local.with_name(local.name + ".part")
    if rec is not None and rec.status == "complete" and local.exists():
        if local.stat().st_size == rec.local_size and (size is None or size == rec.remote_size):
            return "skip"
        return "changed"
    if part.exists() and part.stat().st_size > 0:
        return "resume"
    return "new"


def build_plan(session, download_root: Path, state: StateStore, filters: Filters,
               start: date | None = None, end: date | None = None) -> Plan:
    dirs = [e for e in list_directory(session, "/") if e.is_dir]
    dirs = sort_day_folders(filter_day_folders(dirs, start, end))
    plan = Plan()
    for d in dirs:
        parsed = parse_day_folder(d.name)
        fdate = parsed.date() if parsed else None
        for e in list_directory(session, d.path):
            if e.is_dir:
                continue
            if not _safe_name(e.name):
                log.warning("اسم ملف غير آمن تم تجاهله: %r", e.name)
                continue
            info = parse_product_name(e.name, fdate)
            if not filters.accepts(info):
                continue
            local = local_file_path(download_root, d.name, e.name)
            plan.items.append(PlanItem(d.name, e.name, e.path, e.size, info, local,
                                       _decide(state.get(e.path), local, e.size)))
    return plan


# ---------------------------------------------------------------- التنزيل

class _Interrupted(Exception):
    pass


class _SourceChanged(Exception):
    pass


class DiskFullError(Exception):
    pass


@dataclass
class Snapshot:
    bytes_done: int
    bytes_total: int
    files_done: int
    files_total: int
    files_failed: int
    files_invalid: int
    current: tuple
    paused: bool


@dataclass
class RunResult:
    downloaded: int = 0
    failed: int = 0
    invalid: int = 0
    bytes: int = 0
    stopped: bool = False
    disk_full: bool = False
    auth_failed: bool = False
    network_down: bool = False
    fatal_message: str = ""
    errors: list = field(default_factory=list)

    def summary_ar(self) -> str:
        lines = [f"اكتمل تنزيل {self.downloaded} ملف ({human_size(self.bytes)})"]
        if self.invalid:
            lines.append(f"{self.invalid} ملف فشل التحقق من بنيته (حُفظ بامتداد .invalid)")
        if self.failed:
            lines.append(f"{self.failed} ملف فشل تنزيله (انظر السجل)")
        if self.stopped:
            lines.append("أُوقف التنزيل؛ الملفات الجزئية (.part) محفوظة وستُستكمل في التشغيل التالي")
        if self.disk_full:
            lines.append("توقّف التنزيل: المساحة الحرة غير كافية")
        if self.auth_failed:
            lines.append("توقّف التنزيل: فشل تسجيل الدخول")
        if self.network_down:
            lines.append("توقّف التنزيل: الاتصال غير مستقر أو مقطوع")
        if self.fatal_message:
            lines.append(self.fatal_message)
        return "\n".join(lines)


class DownloadManager:
    def __init__(self, settings: ConnectionSettings, state: StateStore, *,
                 factory=default_ftp_factory, sleep: Callable[[float], None] = time.sleep,
                 max_parallel: int = 1, min_free_bytes: int = 0, blocksize: int = 256 * 1024,
                 on_progress: Callable[[Snapshot], None] | None = None, progress_interval: float = 0.25):
        self.settings, self.state, self.factory, self.sleep = settings, state, factory, sleep
        self.max_parallel = max(1, min(int(max_parallel), 3))
        self.min_free_bytes, self.blocksize = int(min_free_bytes), blocksize
        self.on_progress, self.progress_interval = on_progress, progress_interval
        self._stop = threading.Event()
        self._user_stop = False
        self._go = threading.Event()
        self._go.set()
        self._lock = threading.Lock()
        self._queue: deque[PlanItem] = deque()
        self._result = RunResult()
        self._bytes_done = self._bytes_total = self._files_total = 0
        self._current: dict[str, str] = {}
        self._consecutive_failures = 0
        self._last_emit = 0.0

    # --- التحكم
    def pause(self) -> None:
        self._go.clear()

    def resume(self) -> None:
        self._go.set()

    def stop(self) -> None:
        self._user_stop = True
        self._stop.set()
        self._go.set()

    @property
    def paused(self) -> bool:
        return not self._go.is_set()

    @property
    def interrupted(self) -> bool:
        return self._stop.is_set() or not self._go.is_set()

    # --- التشغيل
    def run(self, items: list[PlanItem]) -> RunResult:
        seen, todo = set(), []
        for i in items:
            if i.action != "skip" and i.remote_path not in seen:
                seen.add(i.remote_path)
                todo.append(i)
        self._queue = deque(todo)
        self._files_total = len(todo)
        self._bytes_total = sum(max((i.size or 0) - (i.part_path.stat().st_size if i.action == "resume"
                                                      and i.part_path.exists() else 0), 0) for i in todo)
        workers = [_Worker(self) for _ in range(min(self.max_parallel, max(len(todo), 1)))]
        threads = [threading.Thread(target=w.loop, daemon=True) for w in workers]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for w in workers:
            w.close()
        self._result.stopped = self._user_stop and bool(self._queue)
        self._emit(force=True)
        return self._result

    # --- مساعدات داخلية (خيوط متعددة)
    def _pop(self) -> PlanItem | None:
        with self._lock:
            return self._queue.popleft() if self._queue else None

    def _push_front(self, item: PlanItem) -> None:
        with self._lock:
            self._queue.appendleft(item)

    def _add_bytes(self, n: int, name: str) -> None:
        with self._lock:
            self._bytes_done += n
            self._result.bytes += n
            self._current[name] = name
        self._emit()

    def _start_item(self, name: str) -> None:
        with self._lock:
            self._current[name] = name
        self._emit(force=True)

    def _finish_item(self, name: str, kind: str, message: str = "") -> None:
        with self._lock:
            self._current.pop(name, None)
            if kind == "ok":
                self._result.downloaded += 1
                self._consecutive_failures = 0
            elif kind == "invalid":
                self._result.invalid += 1
            else:
                self._result.failed += 1
                self._result.errors.append(f"{name}: {message}")
        self._emit(force=True)

    def _fatal(self, **flags) -> None:
        with self._lock:
            for k, v in flags.items():
                setattr(self._result, k, v)
        self._stop.set()
        self._go.set()

    def _emit(self, force: bool = False) -> None:
        if not self.on_progress:
            return
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_emit < self.progress_interval:
                return
            self._last_emit = now
            r = self._result
            snap = Snapshot(self._bytes_done, self._bytes_total, r.downloaded + r.invalid + r.failed,
                            self._files_total, r.failed, r.invalid, tuple(self._current.values()), self.paused)
        try:
            self.on_progress(snap)
        except Exception:
            log.exception("خطأ في رد نداء التقدم")


class _Worker:
    def __init__(self, manager: DownloadManager):
        self.m = manager
        self.session = None
        self.cwd: str | None = None

    def close(self) -> None:
        session, self.session = self.session, None
        self.cwd = None
        if session is not None:
            try:
                session.close()
            except Exception:
                # Cleanup errors must not mask the original download result or
                # terminate a worker before its failure is reported to the GUI.
                log.exception("تعذّر إغلاق جلسة FTP للعامل")

    def loop(self) -> None:
        m = self.m
        try:
            while not m._stop.is_set():
                if not m._go.is_set():
                    self.close()  # لا نترك اتصالًا مفتوحًا أثناء الإيقاف المؤقت
                    m._go.wait(0.2)
                    continue
                item = m._pop()
                if item is None:
                    break
                try:
                    self.process(item)
                except _Interrupted:
                    self.close()
                    m._push_front(item)
                    with m._lock:
                        m._current.pop(item.name, None)
                except DiskFullError as exc:
                    self.close()
                    m._push_front(item)
                    m._fatal(disk_full=True, fatal_message=str(exc))
                except AuthenticationError as exc:
                    self.close()
                    m._push_front(item)
                    m._fatal(auth_failed=True, fatal_message=str(exc))
                except FtpError as exc:  # TLS/إعدادات: لا فائدة من المتابعة
                    self.close()
                    m._push_front(item)
                    m._fatal(fatal_message=str(exc))
                except Exception as exc:
                    # A worker-thread exception must reach the GUI result; otherwise
                    # threading prints it and the application can report a false success.
                    self.close()
                    message = f"خطأ داخلي غير متوقع: {type(exc).__name__}: {exc}"
                    log.exception("%s: %s", item.name, message)
                    try:
                        m.state.upsert(item.remote_path, status="failed", last_error=message[:500])
                    except Exception:
                        log.exception("تعذّر تحديث حالة الملف بعد خطأ العامل: %s", item.name)
                    m._finish_item(item.name, "failed", message)
                    m._fatal(fatal_message=f"توقفت المهمة بسبب خطأ داخلي أثناء تنزيل {item.name}: {type(exc).__name__}")
        finally:
            self.close()

    def process(self, item: PlanItem) -> None:
        m, last = self.m, None
        m._start_item(item.name)
        for attempt in range(1, m.settings.max_retries + 1):
            if m.interrupted:
                raise _Interrupted()
            try:
                if self.session is None:
                    self.session = open_session(m.settings, m.factory, m.sleep)
                    self.cwd = None
                self.download_one(item)
                return
            except (_Interrupted, DiskFullError, AuthenticationError):
                raise
            except _SourceChanged as exc:
                last = exc
                log.warning("%s: %s", item.name, exc)
                # ECMWF may still be writing the product. Back off before
                # checking its size again instead of immediately polling FTP.
                if attempt < m.settings.max_retries:
                    delay = min(2.0 ** (attempt - 1), 30.0)
                    log.info("%s: إعادة فحص حجم المصدر بعد %.0f ثانية", item.name, delay)
                    m.sleep(delay)
            except NetworkError as exc:
                last = exc
                break  # open_session استنفد محاولاته بالفعل
            except FtpError:
                raise
            except ftplib.error_perm as exc:
                self.close()
                m._finish_item(item.name, "failed", f"رفض الخادم: {exc}")
                return
            except (OSError, EOFError, ftplib.error_temp, ftplib.error_reply) as exc:
                last = exc
                self.close()
                log.warning("%s: انقطاع (%s) المحاولة %d/%d", item.name, type(exc).__name__, attempt,
                            m.settings.max_retries)
                if attempt < m.settings.max_retries:
                    m.sleep(min(2.0 ** (attempt - 1), 30.0))
        self.close()
        msg = f"فشل بعد المحاولات: {last}"
        m.state.upsert(item.remote_path, status="failed", last_error=str(last)[:500])
        m._finish_item(item.name, "failed", msg)
        log.error("%s: %s", item.name, msg)
        with m._lock:
            m._consecutive_failures += 1
            down = m._consecutive_failures >= 3
        if down:
            m._fatal(network_down=True)

    @staticmethod
    def _size(ftp, name: str) -> int | None:
        try:
            return ftp.size(name)
        except (ftplib.error_perm, ftplib.error_reply):
            return None

    def _hash_existing(self, part: Path):
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h

    def _transfer(self, ftp, item: PlanItem, offset: int, h) -> None:
        m, part = self.m, item.part_path
        with open(part, "ab" if offset else "wb") as fh:
            def cb(chunk: bytes) -> None:
                if m.interrupted:
                    raise _Interrupted()
                try:
                    fh.write(chunk)
                except OSError as exc:
                    if exc.errno == errno.ENOSPC:
                        raise DiskFullError("امتلأ القرص أثناء الكتابة") from exc
                    raise
                h.update(chunk)
                m._add_bytes(len(chunk), item.name)
            ftp.retrbinary(f"RETR {item.name}", cb, blocksize=m.blocksize, rest=offset if offset else None)
            try:
                # Detect buffered write failures (notably ENOSPC) before treating
                # the transfer as complete or leaving the file handle.
                fh.flush()
            except OSError as exc:
                if exc.errno == errno.ENOSPC:
                    raise DiskFullError("امتلأ القرص أثناء تفريغ البيانات إلى الملف") from exc
                raise

    def download_one(self, item: PlanItem) -> None:
        m, ftp = self.m, self.session.ftp
        folder = posixpath.dirname(item.remote_path)
        if self.cwd != folder:
            ftp.cwd(folder)
            self.cwd = folder
        ftp.voidcmd("TYPE I")
        remote_size = self._size(ftp, item.name)
        if remote_size is None:
            remote_size = item.size
        final, part = item.local_path, item.part_path
        final.parent.mkdir(parents=True, exist_ok=True)

        offset = part.stat().st_size if part.exists() else 0
        if remote_size is not None and offset > remote_size:
            part.unlink()
            offset = 0
        need = max((remote_size or 0) - offset, 0)
        free = shutil.disk_usage(final.parent).free
        if free - need < m.min_free_bytes:
            raise DiskFullError(f"المساحة الحرة ({human_size(free)}) لا تكفي لتنزيل {item.name} "
                                f"({human_size(need)}) مع الإبقاء على {human_size(m.min_free_bytes)}")

        m.state.upsert(item.remote_path, status="downloading", remote_size=remote_size,
                       local_path=str(final), last_error=None)
        m.state.bump_attempts(item.remote_path)

        h = self._hash_existing(part) if offset else hashlib.sha256()
        if remote_size is None or offset < remote_size or offset == 0:
            try:
                self._transfer(ftp, item, offset, h)
            except (ftplib.error_reply, ftplib.error_perm) as exc:
                if offset > 0 and (isinstance(exc, ftplib.error_reply) or str(exc)[:3] in ("500", "501", "502", "504")):
                    log.info("REST غير مدعوم؛ إعادة التنزيل من البداية: %s", item.name)
                    part.unlink(missing_ok=True)
                    h = hashlib.sha256()
                    self._transfer(ftp, item, 0, h)
                else:
                    raise

        local_size = part.stat().st_size
        size_after = self._size(ftp, item.name)
        if remote_size is not None and local_size < remote_size:
            raise OSError("انتهى النقل قبل اكتمال الملف")
        if (remote_size is not None and local_size > remote_size) or \
                (size_after is not None and size_after != local_size):
            part.unlink(missing_ok=True)
            raise _SourceChanged("تغيّر حجم الملف على الخادم أثناء التنزيل (ما زال يُكتب غالبًا)")

        insp = inspect_file(part)
        sha = h.hexdigest()
        if insp.verdict == "corrupt":
            bad = final.with_name(final.name + ".invalid")
            os.replace(part, bad)
            m.state.upsert(item.remote_path, status="invalid", local_path=str(bad), local_size=local_size,
                           sha256=sha, detected_type=insp.detected_type, validation=insp.problem)
            log.error("%s: فشل التحقق: %s", item.name, insp.problem)
            m._finish_item(item.name, "invalid", insp.problem)
            return
        os.replace(part, final)
        validation = "ok" if insp.verdict == "ok" else f"unverified: {insp.problem}"
        m.state.upsert(item.remote_path, status="complete", local_path=str(final), local_size=local_size,
                       sha256=sha, detected_type=insp.detected_type, validation=validation,
                       downloaded_at=utc_now(), last_error=None)
        log.info("اكتمل: %s (%s, %s)", item.name, human_size(local_size), insp.detected_type)
        m._finish_item(item.name, "ok")
