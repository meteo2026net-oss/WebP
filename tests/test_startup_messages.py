import unittest

from ecmwf_collector.startup_messages import postgres_recovery_details


class PostgresRecoveryMessageTests(unittest.TestCase):
    def test_saved_connection_message_uses_real_line_breaks_and_redacts_error(self):
        details = postgres_recovery_details(
            ConnectionError("password=secret"), False,
            lambda value: value.replace("secret", "[REDACTED]"),
        )
        self.assertIn("السبب: ConnectionError: password=[REDACTED]\n\n", details)
        self.assertIn("\n\nيمكنك استخدام SQLite", details)
        self.assertNotIn(r"\n", details)
        self.assertNotIn("secret", details)

    def test_environment_connection_is_never_offered_for_removal(self):
        details = postgres_recovery_details(RuntimeError("offline"), True, str)
        self.assertIn("ECMWF_POSTGRES_DSN", details)
        self.assertIn("هذه الجلسة فقط", details)
        self.assertNotIn("إزالة اتصال PostgreSQL المحفوظ", details)
        self.assertNotIn(r"\n", details)

    def test_error_message_is_included_without_losing_exception_type(self):
        details = postgres_recovery_details(ValueError("database unavailable"), False, str)
        self.assertTrue(details.startswith("السبب: ValueError: database unavailable"))
        self.assertIn("تحقق من تشغيل خدمة PostgreSQL", details)


if __name__ == "__main__":
    unittest.main()
