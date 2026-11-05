import sys
import types
import unittest
from unittest.mock import patch


class PostgresRoleSecurityTests(unittest.TestCase):
    def _load_store(self, role_flags, elevated_membership=None):
        statements = []

        class FakeConnection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, statement, params=None):
                statement = str(statement)
                statements.append(statement)
                if "FROM pg_roles WHERE rolname = current_user" in statement:
                    return types.SimpleNamespace(fetchone=lambda: role_flags)
                if "pg_has_role(current_user" in statement:
                    return types.SimpleNamespace(fetchone=lambda: elevated_membership)
                if "has_table_privilege" in statement:
                    return types.SimpleNamespace(fetchone=lambda: (True, True, True, True, True))
                return types.SimpleNamespace(fetchone=lambda: None)

        fake_psycopg = types.SimpleNamespace(
            connect=lambda *_args, **_kwargs: FakeConnection()
        )
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            from ecmwf_collector.postgres_state import PostgresStateStore
            store = PostgresStateStore("host=127.0.0.1 dbname=weatherdb")
        return store, statements

    def test_restricted_role_is_allowed_to_initialize_store(self):
        store, statements = self._load_store((False, False, False, False, False))
        self.assertIsNotNone(store)
        self.assertTrue(any("has_table_privilege" in item for item in statements))
        self.assertFalse(any("CREATE TABLE" in item for item in statements))

    def test_superuser_or_role_admin_capability_is_rejected(self):
        for flags in (
            (True, False, False, False, False),
            (False, True, False, False, False),
            (False, False, True, False, False),
            (False, False, False, True, False),
            (False, False, False, False, True),
        ):
            with self.subTest(flags=flags):
                statements = []
                class FakeConnection:
                    def __enter__(self):
                        return self
                    def __exit__(self, *_args):
                        return False
                    def execute(self, statement, params=None):
                        statements.append(str(statement))
                        return types.SimpleNamespace(fetchone=lambda: flags)
                fake_psycopg = types.SimpleNamespace(
                    connect=lambda *_args, **_kwargs: FakeConnection()
                )
                with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
                    from ecmwf_collector.postgres_state import PostgresStateStore
                    with self.assertRaisesRegex(RuntimeError, "رفض الاتصال"):
                        PostgresStateStore("host=127.0.0.1 dbname=weatherdb")
                self.assertFalse(any("CREATE TABLE" in item for item in statements))

    def test_membership_in_elevated_predefined_role_is_rejected(self):
        statements = []
        class FakeConnection:
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False
            def execute(self, statement, params=None):
                statement = str(statement)
                statements.append(statement)
                if "FROM pg_roles WHERE rolname = current_user" in statement:
                    return types.SimpleNamespace(fetchone=lambda: (False, False, False, False, False))
                if "pg_has_role(current_user" in statement:
                    return types.SimpleNamespace(fetchone=lambda: ("pg_read_all_data",))
                if "has_table_privilege" in statement:
                    return types.SimpleNamespace(fetchone=lambda: (True, True, True, True, True))
                return types.SimpleNamespace(fetchone=lambda: None)
        fake_psycopg = types.SimpleNamespace(
            connect=lambda *_args, **_kwargs: FakeConnection()
        )
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            from ecmwf_collector.postgres_state import PostgresStateStore
            with self.assertRaisesRegex(RuntimeError, "عضو في دور"):
                PostgresStateStore("host=127.0.0.1 dbname=weatherdb")
        self.assertFalse(any("CREATE TABLE" in item for item in statements))

    def test_missing_table_privileges_are_rejected_without_ddl(self):
        statements = []
        class FakeConnection:
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False
            def execute(self, statement, params=None):
                statement = str(statement)
                statements.append(statement)
                if "FROM pg_roles WHERE rolname = current_user" in statement:
                    return types.SimpleNamespace(fetchone=lambda: (False, False, False, False, False))
                if "pg_has_role(current_user" in statement:
                    return types.SimpleNamespace(fetchone=lambda: None)
                if "has_table_privilege" in statement:
                    return types.SimpleNamespace(fetchone=lambda: (True, True, False, True, True))
                return types.SimpleNamespace(fetchone=lambda: None)
        fake_psycopg = types.SimpleNamespace(connect=lambda *_args, **_kwargs: FakeConnection())
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            from ecmwf_collector.postgres_state import PostgresStateStore
            with self.assertRaisesRegex(RuntimeError, "صلاحيات القراءة والكتابة"):
                PostgresStateStore("host=127.0.0.1 dbname=weatherdb")
        self.assertFalse(any("CREATE TABLE" in item for item in statements))


if __name__ == "__main__":
    unittest.main()
