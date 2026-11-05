"""الواجهة العربية (RTL): الاتصال، الاستعراض، والتنزيل (المرحلتان 1 و2)."""
from __future__ import annotations

import logging
import posixpath
import socket
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QDate, QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QInputDialog,
)

from ..config import CYCLES, KINDS, AppConfig, project_root, save_config
from ..connection import ConnectionSettings, FtpError, open_session, test_connection
from ..downloader import DownloadManager, Filters, build_plan
from ..listing import RemoteEntry, browse, filter_day_folders, human_size, sort_day_folders
from ..logging_setup import register_secret
from ..secrets_store import SecretStore
from ..state import StateStore

log = logging.getLogger(__name__)

PROTOCOL_CHOICES = [("تلقائي (يفضّل TLS)", "auto"), ("FTPS صريح (TLS)", "ftps"), ("FTP عادي (غير مشفّر)", "ftp")]
KIND_LABELS = {"AN": "تحليل AN", "FM": "مستويات النموذج FM (≈90MB/ملف)",
               "FP": "مستويات الضغط FP", "FS": "السطح FS"}


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.done.emit(self.fn())
        except FtpError as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:
            log.exception("خطأ غير متوقع في مهمة خلفية")
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


class _Bridge(QObject):
    progress = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, cfg: AppConfig, config_path, secrets: SecretStore, state: StateStore):
        super().__init__()
        self.cfg, self.config_path, self.secrets, self.state = cfg, config_path, secrets, state
        self.pool = QThreadPool.globalInstance()
        self._workers: set = set()
        self._cwd = "/"
        self._entries: list[RemoteEntry] = []
        self._manager: DownloadManager | None = None
        self._downloading = False
        self._bridge = _Bridge()
        self._bridge.progress.connect(self._on_progress)
        self.setWindowTitle("ECMWF Data Collector")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1000, 860)
        self._build_ui()
        self._load_from_config()

    # ---------- بناء الواجهة ----------
    def _build_ui(self):
        content = QWidget()
        layout = QVBoxLayout(content)

        conn = QGroupBox("إعدادات الاتصال")
        form = QFormLayout(conn)
        self.host = QLineEdit()
        self.host.setLayoutDirection(Qt.LeftToRight)
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.user = QLineEdit()
        self.user.setLayoutDirection(Qt.LeftToRight)
        self.user.setPlaceholderText("wmo_xx")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setLayoutDirection(Qt.LeftToRight)
        self.protocol = QComboBox()
        for label, value in PROTOCOL_CHOICES:
            self.protocol.addItem(label, value)
        self.passive = QCheckBox("وضع Passive")
        self.allow_plain = QCheckBox("السماح بالرجوع إلى FTP غير مشفّر عند عدم دعم TLS (غير موصى به)")
        self.remember = QCheckBox("حفظ كلمة المرور في Windows Credential Manager")
        self.remember.setEnabled(self.secrets.available)
        for label, w in (("المضيف", self.host), ("المنفذ", self.port), ("اسم المستخدم", self.user),
                         ("كلمة مرور FTP", self.password), ("البروتوكول", self.protocol)):
            form.addRow(label, w)
        form.addRow(self.passive)
        form.addRow(self.allow_plain)
        form.addRow(self.remember)
        btns = QHBoxLayout()
        self.btn_test = QPushButton("اختبار الاتصال")
        self.btn_postgres = QPushButton("ربط PostgreSQL ونقل السجل")
        self.btn_postgres.clicked.connect(self._on_configure_postgres)
        self.btn_save = QPushButton("حفظ الإعدادات")
        self.btn_test.clicked.connect(self._on_test)
        self.btn_save.clicked.connect(self._on_save)
        btns.addWidget(self.btn_test)
        btns.addWidget(self.btn_postgres)
        btns.addWidget(self.btn_save)
        btns.addStretch()
        form.addRow(btns)
        layout.addWidget(conn)

        br = QGroupBox("استعراض الخادم (دون تنزيل)")
        bl = QVBoxLayout(br)
        nav = QHBoxLayout()
        self.path_edit = QLineEdit("/")
        self.path_edit.setReadOnly(True)
        self.path_edit.setLayoutDirection(Qt.LeftToRight)
        self.btn_root = QPushButton("الجذر")
        self.btn_up = QPushButton("مستوى أعلى")
        self.btn_refresh = QPushButton("تحديث")
        self.btn_copy = QPushButton("نسخ القائمة")
        self.btn_root.clicked.connect(lambda: self._navigate("/"))
        self.btn_up.clicked.connect(self._go_up)
        self.btn_refresh.clicked.connect(lambda: self._navigate(self._cwd))
        self.btn_copy.clicked.connect(self._copy_listing)
        for w in (QLabel("المسار:"), self.path_edit, self.btn_root, self.btn_up, self.btn_refresh, self.btn_copy):
            nav.addWidget(w)
        bl.addLayout(nav)

        flt = QHBoxLayout()
        self.use_filter = QCheckBox("تحديد فترة زمنية (للاستعراض والتنزيل)")
        self.d_from = QDateEdit(QDate.currentDate().addDays(-4))
        self.d_to = QDateEdit(QDate.currentDate())
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd-MM-yyyy")
        for w in (self.use_filter, QLabel("من"), self.d_from, QLabel("إلى"), self.d_to):
            flt.addWidget(w)
        flt.addStretch()
        bl.addLayout(flt)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["الاسم", "النوع", "الحجم", "آخر تعديل (UTC)"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setMinimumHeight(220)
        self.table.cellDoubleClicked.connect(self._on_row_open)
        QShortcut(QKeySequence.Copy, self.table, activated=self._copy_selected)
        bl.addWidget(self.table)
        layout.addWidget(br)

        dl = QGroupBox("التنزيل")
        dform = QFormLayout(dl)
        row = QHBoxLayout()
        self.dl_dir = QLineEdit()
        self.dl_dir.setReadOnly(True)
        self.dl_dir.setLayoutDirection(Qt.LeftToRight)
        self.btn_dir = QPushButton("تغيير…")
        self.btn_dir.clicked.connect(self._choose_dir)
        row.addWidget(self.dl_dir, 1)
        row.addWidget(self.btn_dir)
        dform.addRow("مجلد التنزيل", row)
        krow = QHBoxLayout()
        self.kind_boxes: dict[str, QCheckBox] = {}
        for code in KINDS:
            cb = QCheckBox(KIND_LABELS[code])
            self.kind_boxes[code] = cb
            krow.addWidget(cb)
        dform.addRow("أنواع الملفات", krow)
        crow = QHBoxLayout()
        self.cycle_boxes: dict[str, QCheckBox] = {}
        for code in CYCLES:
            cb = QCheckBox(f"{code}:00 UTC")
            self.cycle_boxes[code] = cb
            crow.addWidget(cb)
        dform.addRow("وقت الإصدار", crow)
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 3)
        self.min_free = QSpinBox()
        self.min_free.setRange(0, 100000)
        self.min_free.setSuffix(" GB")
        dform.addRow("تنزيلات متزامنة (يُنصح 1)", self.parallel)
        dform.addRow("مساحة حرة تُترك على القرص", self.min_free)
        act = QHBoxLayout()
        self.btn_preview = QPushButton("معاينة الخطة")
        self.btn_start = QPushButton("بدء التنزيل")
        self.btn_pause = QPushButton("إيقاف مؤقت")
        self.btn_stop = QPushButton("إيقاف آمن")
        self.btn_manifest = QPushButton("تصدير سجل الملفات CSV")
        self.btn_process = QPushButton("معالجة الملفات المنزلة للخرائط")
        self.btn_open_map = QPushButton("فتح خريطة الطقس")
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_preview.clicked.connect(self._on_preview)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_manifest.clicked.connect(self._on_manifest)
        self.btn_process.clicked.connect(self._on_process_downloads)
        self.btn_open_map.clicked.connect(self._on_open_map)
        for b in (self.btn_preview, self.btn_start, self.btn_pause, self.btn_stop, self.btn_manifest, self.btn_process):
            act.addWidget(b)
        act.addStretch()
        dform.addRow(act)
        map_row = QHBoxLayout()
        map_row.addWidget(self.btn_open_map)
        map_row.addStretch()
        dform.addRow(map_row)
        self.pbar = QProgressBar()
        self.pbar.setRange(0, 100)
        self.pbar_label = QLabel("—")
        dform.addRow(self.pbar)
        dform.addRow(self.pbar_label)
        layout.addWidget(dl)

        self.status = QPlainTextEdit()
        self.status.setReadOnly(True)
        self.status.setMinimumHeight(140)
        layout.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)

    # ---------- الإعدادات ----------
    def _load_from_config(self):
        c = self.cfg
        self.host.setText(c.host)
        self.port.setValue(c.port)
        self.user.setText(c.username)
        self.passive.setChecked(c.passive)
        self.allow_plain.setChecked(c.allow_plain_ftp)
        self.remember.setChecked(c.remember_password and self.secrets.available)
        self.protocol.setCurrentIndex(max(self.protocol.findData(c.protocol), 0))
        self.dl_dir.setText(c.download_root)
        for k, cb in self.kind_boxes.items():
            cb.setChecked(k in c.selected_kinds)
        for k, cb in self.cycle_boxes.items():
            cb.setChecked(k in c.selected_cycles)
        self.parallel.setValue(c.max_parallel)
        self.min_free.setValue(c.min_free_gb)
        if self.remember.isChecked():
            saved = self.secrets.get_password(c.username)
            if saved:
                self.password.setText(saved)
                register_secret(saved)

    def _read_cfg(self) -> AppConfig:
        return AppConfig(
            host=self.host.text().strip(), port=self.port.value(), username=self.user.text().strip(),
            passive=self.passive.isChecked(), protocol=self.protocol.currentData(),
            allow_plain_ftp=self.allow_plain.isChecked(), timeout_seconds=self.cfg.timeout_seconds,
            max_retries=self.cfg.max_retries, download_root=self.dl_dir.text() or "downloads",
            remember_password=self.remember.isChecked(),
            selected_kinds=[k for k, cb in self.kind_boxes.items() if cb.isChecked()],
            selected_cycles=[k for k, cb in self.cycle_boxes.items() if cb.isChecked()],
            max_parallel=self.parallel.value(), min_free_gb=self.min_free.value())

    def _settings(self) -> ConnectionSettings | None:
        cfg = self._read_cfg()
        try:
            cfg.validate()
        except ValueError as exc:
            QMessageBox.warning(self, "إعدادات غير صالحة", str(exc))
            return None
        if not cfg.username or not self.password.text():
            QMessageBox.warning(self, "بيانات ناقصة", "أدخل اسم المستخدم وكلمة مرور FTP.")
            return None
        return ConnectionSettings.from_config(cfg, self.password.text())

    def _on_configure_postgres(self):
        if self._downloading or self._workers:
            QMessageBox.information(
                self, "انتظر انتهاء المهمة",
                "أوقف التنزيل وانتظر انتهاء المهام الحالية قبل تغيير قاعدة البيانات.",
            )
            return
        if not isinstance(self.state, StateStore):
            QMessageBox.information(
                self, "PostgreSQL نشط بالفعل",
                "التطبيق يستخدم PostgreSQL حالياً. لم يتم تغيير قاعدة البيانات.",
            )
            return
        dsn, accepted = QInputDialog.getText(
            self,
            "ربط PostgreSQL",
            "أدخل سلسلة اتصال PostgreSQL المحلية (سيُخفى النص):",
            QLineEdit.Password,
        )
        if not accepted or not dsn.strip():
            return

        sqlite_store = self.state
        postgres_store = None
        backup_path = None
        try:
            from ..postgres_state import PostgresStateStore
            from ..tools.migrate_sqlite_to_postgres import create_sqlite_backup

            state_path = project_root() / "state" / "state.db"
            backup_dir = project_root() / "state" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            backup_path = backup_dir / f"state-before-postgres-{stamp}.db"
            create_sqlite_backup(state_path, backup_path)

            source_records = sqlite_store.all_records()
            postgres_store = PostgresStateStore(dsn.strip())
            postgres_store.import_records(source_records)
            target_records = postgres_store.all_records()
            target_by_path = {record.remote_path: record for record in target_records}
            mismatches = [
                record.remote_path for record in source_records
                if target_by_path.get(record.remote_path) != record
            ]
            if mismatches:
                raise RuntimeError(
                    f"التحقق من الترحيل لم ينجح لعدد {len(mismatches)} سجلات."
                )
            if not self.secrets.set_postgres_dsn(dsn.strip()):
                raise RuntimeError(
                    "تعذّر حفظ بيانات الاتصال في مخزن بيانات اعتماد Windows؛ "
                    "لم يتم تبديل قاعدة البيانات الحالية."
                )

            self.state = postgres_store
            postgres_store = None
            sqlite_store.close()
            self._log(
                f"تم ربط PostgreSQL والتحقق من {len(source_records)} سجلات. "
                f"نسخة SQLite الاحتياطية محفوظة في: {backup_path}"
            )
            QMessageBox.information(
                self, "اكتمل ربط PostgreSQL",
                f"تم نقل السجل والتحقق منه بنجاح.\\n"
                f"عدد السجلات: {len(source_records)}\\n"
                f"نسخة SQLite الاحتياطية: {backup_path}\\n"
                "ستستخدم الجلسات القادمة PostgreSQL تلقائياً.",
            )
        except Exception as exc:
            if postgres_store is not None:
                postgres_store.close()
            self._log(f"تعذّر ربط PostgreSQL؛ بقيت قاعدة SQLite الحالية كما هي: {type(exc).__name__}")
            QMessageBox.critical(
                self, "فشل ربط PostgreSQL",
                f"لم يتم تبديل قاعدة البيانات الحالية.\\n"
                f"السبب: {type(exc).__name__}: {exc}\\n"
                f"النسخة الاحتياطية إن أُنشئت: {backup_path or 'لم تُنشأ'}",
            )

    def _on_save(self):
        cfg = self._read_cfg()
        try:
            save_config(cfg, self.config_path)
        except Exception as exc:
            QMessageBox.critical(self, "تعذّر الحفظ", str(exc))
            return
        self.cfg = cfg
        if cfg.remember_password and self.password.text():
            ok = self.secrets.set_password(cfg.username, self.password.text())
            self._log("حُفظت كلمة المرور في مخزن الأسرار." if ok else "تعذّر الحفظ في مخزن الأسرار.")
        elif not cfg.remember_password:
            self.secrets.delete_password(cfg.username)
        self._log("حُفظت الإعدادات (بدون كلمة المرور).")

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "اختر مجلد التنزيل", str(self._download_root()))
        if d:
            self.dl_dir.setText(d)

    def _download_root(self) -> Path:
        p = Path(self.dl_dir.text() or "downloads")
        return p if p.is_absolute() else project_root() / p

    # ---------- المهام الخلفية ----------
    def _run(self, fn, on_done, busy=True):
        w = Worker(fn)
        self._workers.add(w)

        def done(res):
            self._workers.discard(w)
            self._busy(False)
            on_done(res)

        def failed(msg):
            self._workers.discard(w)
            self._busy(False)
            self._log(f"خطأ: {msg}")

        w.signals.done.connect(done)
        w.signals.failed.connect(failed)
        if busy:
            self._busy(True)
        self.pool.start(w)

    def _busy(self, busy: bool):
        locked = busy or self._downloading
        for b in (self.btn_test, self.btn_postgres, self.btn_root, self.btn_up, self.btn_refresh, self.btn_copy,
                  self.btn_preview, self.btn_start, self.btn_process):
            b.setEnabled(not locked)

    def _on_test(self):
        s = self._settings()
        if not s:
            return
        self._log("جارٍ اختبار الاتصال…")
        self._run(lambda: test_connection(s), self._test_done)

    def _test_done(self, r):
        if r.ok:
            self._log(f"✔ {r.message_ar}\nالبروتوكول: {r.protocol}\nالمجلد الحالي: {r.cwd or '—'}")
            self._navigate("/")
        else:
            self._log(f"✘ {r.message_ar}")

    # ---------- الاستعراض ----------
    def _navigate(self, path: str):
        s = self._settings()
        if not s:
            return
        self._log(f"استعراض: {path}")
        self._run(lambda: browse(s, path), lambda entries: self._show(path, entries))

    def _show(self, path: str, entries: list[RemoteEntry]):
        self._cwd = path
        self.path_edit.setText(path)
        if path == "/":
            if self.use_filter.isChecked():
                entries = filter_day_folders(entries, self.d_from.date().toPython(), self.d_to.date().toPython())
            entries = sort_day_folders(entries) + [e for e in entries if not e.is_dir]
        self._entries = entries
        self.table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            mod = e.modified.strftime("%Y-%m-%d %H:%M:%S") if e.modified else "—"
            for c, text in enumerate((e.name, "مجلد" if e.is_dir else "ملف",
                                      "" if e.is_dir else human_size(e.size), mod)):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self._log(f"عدد العناصر: {len(entries)}")

    def _on_row_open(self, row: int, _col: int):
        if 0 <= row < len(self._entries) and self._entries[row].is_dir:
            self._navigate(self._entries[row].path)

    def _go_up(self):
        self._navigate(posixpath.dirname(self._cwd.rstrip("/")) or "/")

    def _rows_text(self, entries) -> str:
        lines = [f"المسار: {self._cwd}", "الاسم\tالنوع\tالحجم(بايت)\tآخر تعديل UTC"]
        for e in entries:
            mod = e.modified.strftime("%Y-%m-%d %H:%M:%S") if e.modified else ""
            lines.append(f"{e.name}\t{'dir' if e.is_dir else 'file'}\t{'' if e.size is None else e.size}\t{mod}")
        return "\n".join(lines)

    def _copy_listing(self):
        text = self._rows_text(self._entries)
        QGuiApplication.clipboard().setText(text)
        try:
            out = project_root() / "state" / "listing_last.txt"
            out.parent.mkdir(exist_ok=True)
            out.write_text(text, encoding="utf-8")
            self._log(f"نُسخت {len(self._entries)} عناصر إلى الحافظة وحُفظت في: {out}")
        except OSError as exc:
            self._log(f"نُسخت إلى الحافظة، لكن تعذّر حفظ الملف: {exc}")

    def _copy_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        QGuiApplication.clipboard().setText(
            self._rows_text([self._entries[r] for r in rows if r < len(self._entries)]))

    # ---------- التنزيل ----------
    def _filters(self) -> Filters:
        return Filters(kinds=frozenset(k for k, cb in self.kind_boxes.items() if cb.isChecked()),
                       cycles=frozenset(k for k, cb in self.cycle_boxes.items() if cb.isChecked()),
                       include_unknown=True)

    def _build_plan(self, then):
        s = self._settings()
        if not s:
            return
        if not self._filters().kinds or not self._filters().cycles:
            QMessageBox.warning(self, "تصفية فارغة", "اختر نوع ملفات ووقت إصدار واحدًا على الأقل.")
            return
        filters, root, state = self._filters(), self._download_root(), self.state
        start = end = None
        if self.use_filter.isChecked():
            start, end = self.d_from.date().toPython(), self.d_to.date().toPython()
        self._log("جارٍ بناء خطة التنزيل (قراءة القوائم فقط)…")

        def work():
            with open_session(s) as session:
                return build_plan(session, root, state, filters, start, end)

        self._run(work, then)

    def _on_preview(self):
        self._build_plan(lambda plan: self._log("خطة التنزيل:\n" + plan.summary_ar()))

    def _on_start(self):
        self._build_plan(self._confirm_and_start)

    def _confirm_and_start(self, plan):
        self._log("خطة التنزيل:\n" + plan.summary_ar())
        if not plan.to_download:
            self._log("لا توجد ملفات تحتاج إلى تنزيل.")
            return
        ans = QMessageBox.question(self, "تأكيد التنزيل", plan.summary_ar() + "\n\nهل تريد البدء؟")
        if ans != QMessageBox.Yes:
            return
        s = self._settings()
        if not s:
            return
        cfg = self._read_cfg()
        self._manager = DownloadManager(
            s, self.state, max_parallel=cfg.max_parallel, min_free_bytes=cfg.min_free_gb * 1024 ** 3,
            on_progress=self._bridge.progress.emit)
        manager, items = self._manager, plan.to_download
        self._downloading = True
        self._busy(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self.btn_pause.setText("إيقاف مؤقت")
        self._log(f"بدأ التنزيل: {len(items)} ملف")
        self._run(lambda: manager.run(items), self._download_done, busy=False)

    def _download_done(self, result):
        self._downloading = False
        self._manager = None
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self._busy(False)
        self._log("انتهى:\n" + result.summary_ar())

    def _on_progress(self, snap):
        total = max(snap.bytes_total, 1)
        self.pbar.setValue(min(100, int(snap.bytes_done * 100 / total)))
        cur = "، ".join(snap.current[:3])
        self.pbar_label.setText(
            f"{human_size(snap.bytes_done)} / {human_size(snap.bytes_total)} — ملفات: "
            f"{snap.files_done}/{snap.files_total} — فشل: {snap.files_failed} — غير صالح: {snap.files_invalid}"
            + (" — متوقف مؤقتًا" if snap.paused else "") + (f" — الآن: {cur}" if cur else ""))

    def _on_pause(self):
        m = self._manager
        if not m:
            return
        if m.paused:
            m.resume()
            self.btn_pause.setText("إيقاف مؤقت")
            self._log("استُؤنف التنزيل.")
        else:
            m.pause()
            self.btn_pause.setText("استئناف")
            self._log("إيقاف مؤقت: تُحفظ الأجزاء المنزّلة وتُقطع الاتصالات حتى الاستئناف.")

    def _on_stop(self):
        if self._manager:
            self._manager.stop()
            self._log("جارٍ الإيقاف الآمن… تبقى الملفات الجزئية (.part) وتُستكمل لاحقًا.")

    def _on_open_map(self):
        url = "http://127.0.0.1:8765/map_viewer/"
        try:
            with socket.create_connection(("127.0.0.1", 8765), timeout=0.4):
                webbrowser.open(url)
                self._log(f"فتح عارض الخريطة: {url}")
                return
        except OSError:
            pass
        try:
            if getattr(sys, "frozen", False):
                command = [sys.executable, "--map-server"]
                working_directory = str(project_root())
            else:
                command = [sys.executable, str(project_root() / "serve_map.py")]
                working_directory = str(project_root())
            subprocess.Popen(
                command,
                cwd=working_directory,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            self._log("جارٍ تشغيل خادم الخريطة المحلي وفتح المتصفح…")
        except OSError as exc:
            self._log(f"تعذّر تشغيل خادم الخريطة: {exc}")

    def _on_process_downloads(self):
        download_root = self._download_root()
        output_root = project_root() / "output" / "map_data"
        self._log(f"بدء فحص ملفات GRIB المنزلة وتحويل الحقول المتوافقة: {download_root}")

        def work():
            from ..tools.process_downloads import process_tree
            return process_tree(download_root, output_root)

        self._run(work, self._process_downloads_done)

    def _process_downloads_done(self, report):
        converted = report.get("converted", [])
        failed = report.get("failed", [])
        layer_count = sum(item.get("layers", 0) for item in converted)
        self._log(
            f"انتهت المعالجة: ملفات حُوّلت={len(converted)}، طبقات={layer_count}، "
            f"ملفات لم تُحوّل أو تعذّر فحصها={len(failed)}.\n"
            f"قائمة الطبقات: {project_root() / 'output' / 'map_data' / 'manifest.json'}\n"
            "لعرضها شغّل serve_map.py من مجلد المشروع ثم افتح الرابط الذي يظهر."
        )
        for item in failed[:10]:
            self._log(f"لم تتم معالجة {item.get('source')}: {item.get('error')}")

    def _on_manifest(self):
        out = project_root() / "state" / "manifest.csv"
        try:
            n = self.state.export_csv(out)
            self._log(f"صُدّر سجل {n} ملف إلى: {out}")
        except OSError as exc:
            self._log(f"تعذّر التصدير: {exc}")

    def closeEvent(self, event):
        if self._manager:
            self._manager.stop()
            self.pool.waitForDone(10000)
        super().closeEvent(event)

    def _log(self, msg: str):
        log.info(msg.replace("\n", " | "))
        self.status.appendPlainText(msg)
