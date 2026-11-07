import unittest
from unittest.mock import patch

from ecmwf_collector.gui.main_window import MainWindow
from ecmwf_collector.logging_setup import clear_secrets, register_secret


class FakeStatus:
    def __init__(self):
        self.lines = []

    def appendPlainText(self, value):
        self.lines.append(value)


class GuiLogRedactionTests(unittest.TestCase):
    def test_status_widget_and_log_receive_redacted_connection_secret(self):
        secret = "postgresql://collector:very-private-password@127.0.0.1/weather"
        window = type("Window", (), {"status": FakeStatus()})()
        register_secret(secret)
        try:
            with patch("ecmwf_collector.gui.main_window.log.info") as info:
                MainWindow._log(window, f"Connection failure for {secret}")

            displayed = "\n".join(window.status.lines)
            logged = info.call_args.args[0]
            self.assertNotIn(secret, displayed)
            self.assertNotIn(secret, logged)
            self.assertIn("********", displayed)
            self.assertIn("********", logged)
        finally:
            clear_secrets()


if __name__ == "__main__":
    unittest.main()
