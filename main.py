"""Run the ECMWF desktop collector from source or a PyInstaller bundle."""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ecmwf_collector.config import load_config, project_root
from ecmwf_collector.logging_setup import setup_logging
from ecmwf_collector.secrets_store import SecretStore
from ecmwf_collector.state_backend import (
    EXIT, REMOVE_SAVED_AND_USE_SQLITE, SQLITE_ONCE, open_state_store,
)
from ecmwf_collector.logging_setup import redact


def main() -> int:
    if "--map-server" in sys.argv[1:]:
        try:
            from serve_map import main as map_main
            map_main(open_browser="--no-browser" not in sys.argv[1:])
            return 0
        except Exception:
            # Windowed PyInstaller builds have no visible console; preserve
            # startup tracebacks in the writable per-user data directory.
            import traceback
            log_dir = project_root() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with (log_dir / "map_server_startup.log").open("a", encoding="utf-8") as log:
                log.write(traceback.format_exc())
                log.write("\n")
            return 1

    data_root = project_root()
    for name in ("config", "downloads", "processed", "logs", "state", "output"):
        (data_root / name).mkdir(parents=True, exist_ok=True)
    setup_logging(data_root / "logs")
    config_path = data_root / "config" / "settings.json"
    cfg = load_config(config_path)
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from ecmwf_collector.gui.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    secrets = SecretStore()
    postgres_dsn = os.environ.get("ECMWF_POSTGRES_DSN", "").strip() or secrets.get_postgres_dsn()

    def recover_postgres(exc: Exception, environment_dsn: bool) -> str:
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("تعذّر الاتصال بقاعدة PostgreSQL")
        box.setText("لم يتمكن التطبيق من فتح PostgreSQL. بيانات SQLite الأصلية لم تُحذف أو تُعدّل.")
        details = (
            f"السبب: {type(exc).__name__}: {redact(str(exc))}\\n\\n"
            "تحقق من تشغيل خدمة PostgreSQL وصحة إعداد الاتصال."
        )
        if environment_dsn:
            details += (
                "\\n\\nمصدر الاتصال هو متغير البيئة ECMWF_POSTGRES_DSN؛ "
                "سيبقى كما هو، وسيؤدي اختيار SQLite إلى تجاوز PostgreSQL لهذه الجلسة فقط."
            )
        else:
            details += (
                "\\n\\nيمكنك استخدام SQLite لهذه الجلسة فقط، أو إزالة اتصال PostgreSQL "
                "المحفوظ من مخزن بيانات اعتماد Windows والعودة إلى SQLite بشكل دائم."
            )
        box.setInformativeText(details)
        sqlite_once = box.addButton("استخدام SQLite لهذه الجلسة", QMessageBox.AcceptRole)
        remove_saved = None
        if not environment_dsn:
            remove_saved = box.addButton(
                "إزالة اتصال PostgreSQL المحفوظ والعودة إلى SQLite",
                QMessageBox.DestructiveRole,
            )
        cancel = box.addButton("إغلاق", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is sqlite_once:
            return SQLITE_ONCE
        if remove_saved is not None and clicked is remove_saved:
            return REMOVE_SAVED_AND_USE_SQLITE
        return EXIT

    try:
        state_store = open_state_store(data_root, secrets, postgres_dsn, recover_postgres)
    except Exception as exc:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(
            None,
            "تعذّر الرجوع إلى SQLite",
            f"لم يغيّر التطبيق قاعدة البيانات.\\nالسبب: {type(exc).__name__}: {redact(str(exc))}",
        )
        return 2
    if state_store is None:
        return 2
    window = MainWindow(cfg, config_path, secrets, state_store)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
