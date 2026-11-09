import unittest
from unittest.mock import Mock

from main import _select_postgres_dsn


class PreflightDatabaseIsolationTests(unittest.TestCase):
    def test_preflight_bypasses_environment_and_credential_vault(self):
        secrets = Mock()
        result = _select_postgres_dsn(
            secrets,
            preflight_sqlite=True,
            environ={"ECMWF_POSTGRES_DSN": "postgresql://remote.example/private"},
        )
        self.assertIsNone(result)
        secrets.get_postgres_dsn.assert_not_called()

    def test_normal_startup_prefers_environment_dsn(self):
        secrets = Mock()
        result = _select_postgres_dsn(
            secrets,
            environ={"ECMWF_POSTGRES_DSN": "postgresql://env/db"},
        )
        self.assertEqual(result, "postgresql://env/db")
        secrets.get_postgres_dsn.assert_not_called()

    def test_normal_startup_falls_back_to_credential_vault(self):
        secrets = Mock()
        secrets.get_postgres_dsn.return_value = "postgresql://saved/db"
        result = _select_postgres_dsn(secrets, environ={})
        self.assertEqual(result, "postgresql://saved/db")
        secrets.get_postgres_dsn.assert_called_once_with()

    def test_blank_environment_value_uses_credential_vault(self):
        secrets = Mock()
        secrets.get_postgres_dsn.return_value = "postgresql://saved/db"
        result = _select_postgres_dsn(
            secrets, environ={"ECMWF_POSTGRES_DSN": "   "}
        )
        self.assertEqual(result, "postgresql://saved/db")
        secrets.get_postgres_dsn.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
