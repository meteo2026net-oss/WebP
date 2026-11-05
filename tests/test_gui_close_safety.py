import unittest
from unittest.mock import patch

from ecmwf_collector.gui.main_window import MainWindow, QMessageBox


class FakeCloseEvent:
    def __init__(self):
        self.ignored = False

    def ignore(self):
        self.ignored = True


class FakeWindow:
    def __init__(self):
        self._workers = {object()}
        self._downloading = False
        self._manager = None
        self._close_when_idle = False
        self.messages = []

    def _log(self, message):
        self.messages.append(message)

    def close(self):
        self.messages.append("closed")


class CloseSafetyTests(unittest.TestCase):
    def test_close_is_deferred_when_background_worker_is_active(self):
        window = FakeWindow()
        event = FakeCloseEvent()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            MainWindow.closeEvent(window, event)

        self.assertTrue(event.ignored)
        self.assertTrue(window._close_when_idle)
        self.assertTrue(any("سيبقى التطبيق مفتوحاً" in item for item in window.messages))

    def test_declining_wait_keeps_window_open_and_does_not_schedule_close(self):
        window = FakeWindow()
        event = FakeCloseEvent()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
            MainWindow.closeEvent(window, event)

        self.assertTrue(event.ignored)
        self.assertFalse(window._close_when_idle)

    def test_deferred_close_is_scheduled_only_after_all_workers_finish(self):
        window = FakeWindow()
        window._workers.clear()
        window._close_when_idle = True
        with patch("ecmwf_collector.gui.main_window.QTimer.singleShot") as single_shot:
            MainWindow._finish_close_if_idle(window)

        self.assertFalse(window._close_when_idle)
        single_shot.assert_called_once_with(0, window.close)

    def test_deferred_close_waits_while_another_worker_remains(self):
        window = FakeWindow()
        window._close_when_idle = True
        with patch("ecmwf_collector.gui.main_window.QTimer.singleShot") as single_shot:
            MainWindow._finish_close_if_idle(window)

        self.assertTrue(window._close_when_idle)
        single_shot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
