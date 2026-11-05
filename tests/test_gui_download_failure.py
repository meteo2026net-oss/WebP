import unittest
from unittest.mock import patch

from ecmwf_collector.gui.main_window import MainWindow, QMessageBox


class FakeControl:
    def __init__(self):
        self.enabled = True
        self.text = ""

    def setEnabled(self, enabled):
        self.enabled = enabled

    def setText(self, text):
        self.text = text


class FakeDownloadWindow:
    def __init__(self):
        self._downloading = True
        self._manager = object()
        self._workers = set()
        self._close_when_idle = False
        self.btn_pause = FakeControl()
        self.btn_stop = FakeControl()
        self.pbar_label = FakeControl()
        self.messages = []
        self.busy_state = None

    def _busy(self, busy):
        self.busy_state = busy

    def _log(self, message):
        self.messages.append(message)

    def close(self):
        self.messages.append("closed")


class DownloadFailureRecoveryTests(unittest.TestCase):
    def test_worker_failure_resets_download_state_and_controls(self):
        window = FakeDownloadWindow()

        with patch.object(QMessageBox, "warning") as warning:
            MainWindow._download_failed(window, "network worker crashed")

        self.assertFalse(window._downloading)
        self.assertIsNone(window._manager)
        self.assertFalse(window.btn_pause.enabled)
        self.assertFalse(window.btn_stop.enabled)
        self.assertEqual(window.btn_pause.text, "إيقاف مؤقت")
        self.assertIn("توقف التنزيل", window.pbar_label.text)
        self.assertFalse(window.busy_state)
        self.assertTrue(any("network worker crashed" in item for item in window.messages))
        warning.assert_called_once()

    def test_download_failure_releases_deferred_safe_close(self):
        window = FakeDownloadWindow()
        window._close_when_idle = True

        with patch.object(QMessageBox, "warning"), patch(
            "ecmwf_collector.gui.main_window.QTimer.singleShot"
        ) as single_shot:
            MainWindow._download_failed(window, "worker failure")
            MainWindow._finish_close_if_idle(window)

        self.assertFalse(window._close_when_idle)
        single_shot.assert_called_once_with(0, window.close)


if __name__ == "__main__":
    unittest.main()
