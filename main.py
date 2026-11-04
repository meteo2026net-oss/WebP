"""نقطة التشغيل: python main.py"""
import sys

from ecmwf_collector.config import load_config, project_root
from ecmwf_collector.logging_setup import setup_logging
from ecmwf_collector.secrets_store import SecretStore
from ecmwf_collector.state import StateStore


def main() -> int:
    root = project_root()
    for d in ("config", "downloads", "processed", "logs", "state"):
        (root / d).mkdir(exist_ok=True)
    setup_logging(root / "logs")
    config_path = root / "config" / "settings.json"
    cfg = load_config(config_path)

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from ecmwf_collector.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    win = MainWindow(cfg, config_path, SecretStore(), StateStore(root / "state" / "state.db"))
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
