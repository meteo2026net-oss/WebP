import unittest
from pathlib import Path
from unittest.mock import patch

from ecmwf_collector.gui.main_window import MainWindow, QMessageBox


class FakeWindow:
    def __init__(self):
        self.messages = []

    def _log(self, message):
        self.messages.append(message)


class PostgresRestoreCompletionTests(unittest.TestCase):
    def test_success_reports_verified_record_count_without_database_io_in_gui_callback(self):
        window = FakeWindow()
        archive = Path("backup.dump")
        safety = Path("safety.dump")

        with patch.object(QMessageBox, "information") as info:
            MainWindow._postgres_restore_done(window, archive, safety, 42)

        self.assertTrue(any("عدد السجلات: 42" in message for message in window.messages))
        info.assert_called_once()
        self.assertIn("42", info.call_args.args[2])

    def test_post_restore_app_login_check_failure_is_warning_not_restore_failure(self):
        window = FakeWindow()
        archive = Path("backup.dump")
        safety = Path("safety.dump")

        with patch.object(QMessageBox, "warning") as warning:
            MainWindow._postgres_restore_done(
                window, archive, safety, None, "OperationalError: app login refused"
            )

        self.assertTrue(any("اكتملت الاستعادة" in message for message in window.messages))
        self.assertTrue(any(str(safety) in message for message in window.messages))
        warning.assert_called_once()
        self.assertIn("app login refused", warning.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
