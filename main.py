"""Run the ECMWF desktop collector from a source checkout."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ecmwf_collector.config import load_config
from ecmwf_collector.logging_setup import setup_logging
from ecmwf_collector.secrets_store import SecretStore
from ecmwf_collector.state import StateStore


def main() -> int:
    for name in ("config", "downloads", "processed", "logs", "state", "output"):
        (ROOT / name).mkdir(exist_ok=True)
    setup_logging(ROOT / "logs")
    config_path = ROOT / "config" / "settings.json"
    cfg = load_config(config_path)
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from ecmwf_collector.gui.main_window import MainWindow
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    window = MainWindow(cfg, config_path, SecretStore(), StateStore(ROOT / "state" / "state.db"))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
