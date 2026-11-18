"""Windows/Qt desktop startup smoke test for the ECMWF controls."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ecmwf_collector.config import AppConfig
from ecmwf_collector.gui.main_window import MainWindow
from ecmwf_collector.state import StateStore


class NoSecrets:
    available = False

    def get_password(self, _username: str):
        return None


def main() -> int:
    app = QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = AppConfig(download_root=str(root / "downloads"))
        config.validate()
        state = StateStore(root / "state.db")
        window = None
        try:
            window = MainWindow(config, root / "settings.json", NoSecrets(), state)
            assert window.ecmwf_model.count() == 3
            assert window.ecmwf_model.itemData(0) == "ifs"
            assert window.ecmwf_model.itemData(1) == "aifs-single"
            assert window.ecmwf_model.itemData(2) == "aifs-ens"
            assert window.ecmwf_resolution.currentData() == "0p25"
            assert window.ecmwf_step.value() == 24
            assert window.ecmwf_step_end.value() == 24
            window.ecmwf_model.setCurrentIndex(2)
            assert window.ecmwf_member.isVisible()
            assert window.ecmwf_resolution.currentData() == "0p25"
            window.ecmwf_model.setCurrentIndex(0)
            assert not window.ecmwf_member.isVisible()
            print("Windows Qt UI startup and ECMWF controls: OK")
        finally:
            if window is not None:
                window.close()
            state.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
