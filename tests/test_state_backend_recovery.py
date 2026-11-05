import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecmwf_collector import state_backend


class _Secrets:
    def __init__(self, delete_result=True):
        self.delete_result = delete_result
        self.deleted = 0

    def delete_postgres_dsn(self):
        self.deleted += 1
        return self.delete_result


class StateBackendRecoveryTests(unittest.TestCase):
    def test_without_postgres_uses_existing_sqlite_backend(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
            state_backend, "StateStore", return_value="sqlite"
        ) as sqlite, patch.object(state_backend, "PostgresStateStore") as postgres:
            result = state_backend.open_state_store(Path(temp), _Secrets(), None, self.fail)
        self.assertEqual(result, "sqlite")
        sqlite.assert_called_once_with(Path(temp) / "state" / "state.db")
        postgres.assert_not_called()

    def test_failed_postgres_can_fall_back_to_sqlite_for_this_session(self):
        secrets = _Secrets()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True), patch.object(
            state_backend, "PostgresStateStore", side_effect=ConnectionError("offline")
        ), patch.object(state_backend, "StateStore", return_value="sqlite") as sqlite:
            result = state_backend.open_state_store(
                Path(temp), secrets, "postgresql://app@localhost/db",
                lambda exc, from_env: state_backend.SQLITE_ONCE,
            )
        self.assertEqual(result, "sqlite")
        self.assertEqual(secrets.deleted, 0)
        sqlite.assert_called_once_with(Path(temp) / "state" / "state.db")

    def test_explicit_remove_deletes_only_saved_credential_then_uses_sqlite(self):
        secrets = _Secrets()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True), patch.object(
            state_backend, "PostgresStateStore", side_effect=ConnectionError("offline")
        ), patch.object(state_backend, "StateStore", return_value="sqlite"):
            result = state_backend.open_state_store(
                Path(temp), secrets, "postgresql://app@localhost/db",
                lambda exc, from_env: state_backend.REMOVE_SAVED_AND_USE_SQLITE,
            )
        self.assertEqual(result, "sqlite")
        self.assertEqual(secrets.deleted, 1)

    def test_environment_dsn_cannot_be_removed_as_saved_credential(self):
        secrets = _Secrets()
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            os.environ, {"ECMWF_POSTGRES_DSN": "postgresql://env/db"}
        ), patch.object(state_backend, "PostgresStateStore", side_effect=ConnectionError("offline")):
            with self.assertRaisesRegex(ValueError, "environment"):
                state_backend.open_state_store(
                    Path(temp), secrets, "postgresql://env/db",
                    lambda exc, from_env: state_backend.REMOVE_SAVED_AND_USE_SQLITE,
                )
        self.assertEqual(secrets.deleted, 0)

    def test_cancel_leaves_postgres_credential_untouched(self):
        secrets = _Secrets()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True), patch.object(
            state_backend, "PostgresStateStore", side_effect=ConnectionError("offline")
        ):
            result = state_backend.open_state_store(
                Path(temp), secrets, "postgresql://app@localhost/db",
                lambda exc, from_env: state_backend.EXIT,
            )
        self.assertIsNone(result)
        self.assertEqual(secrets.deleted, 0)

    def test_failed_credential_removal_does_not_switch_database(self):
        secrets = _Secrets(delete_result=False)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True), patch.object(
            state_backend, "PostgresStateStore", side_effect=ConnectionError("offline")
        ), patch.object(state_backend, "StateStore") as sqlite:
            with self.assertRaisesRegex(RuntimeError, "credential vault"):
                state_backend.open_state_store(
                    Path(temp), secrets, "postgresql://app@localhost/db",
                    lambda exc, from_env: state_backend.REMOVE_SAVED_AND_USE_SQLITE,
                )
        sqlite.assert_not_called()

    @staticmethod
    def fail(*args):
        raise AssertionError("Recovery callback must not be called")


if __name__ == "__main__":
    unittest.main()
