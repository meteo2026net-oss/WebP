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
from ecmwf_collector.state import StateStore


def main() -> int:
    if "--map-server" in sys.argv[1:]:
        from serve_map import main as map_main
        map_main(open_browser="--no-browser" not in sys.argv[1:])
        return 0

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
    if postgres_dsn:
        from PySide6.QtWidgets import QMessageBox
        from ecmwf_collector.postgres_state import PostgresStateStore
        try:
            state_store = PostgresStateStore(postgres_dsn)
        except Exception as exc:
            QMessageBox.critical(
                None,
                "تعذّر الاتصال بقاعدة PostgreSQL",
                "تعذّر فتح قاعدة PostgreSQL المحفوظة. لم يتم تحويل البيانات أو حذفها.\\n\\n"
                f"التفاصيل: {type(exc).__name__}: {exc}\\n\\n"
                "تحقق من تشغيل خدمة PostgreSQL وصحة إعداد الاتصال. "
                "يمكن إزالة الاتصال المحفوظ من مخزن بيانات اعتماد Windows "
                "للعودة إلى SQLite في التشغيل التالي.",
            )
            return 2
    else:
        state_store = StateStore(data_root / "state" / "state.db")
    window = MainWindow(cfg, config_path, secrets, state_store)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
