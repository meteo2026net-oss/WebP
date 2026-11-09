import unittest

from ecmwf_collector.postgres_security import (
    PostgresRoleError,
    assert_postgres_application_role,
)


class FakeConnection:
    def __init__(self, *, role=(False, False, False, False, False),
                 elevated=None, access=(True, True, True), tables=None):
        self.role = role
        self.elevated = elevated
        self.access = access
        self.tables = tables or {}
        self.calls = []

    def execute(self, statement, params=None):
        statement = str(statement)
        self.calls.append((statement, params))
        if "FROM pg_roles WHERE rolname = current_user" in statement:
            value = self.role
        elif "pg_has_role(current_user" in statement:
            value = self.elevated
        elif "has_database_privilege" in statement:
            value = self.access
        elif "to_regclass" in statement:
            name = params[0]
            value = self.tables.get(name, (False, False))
        else:
            raise AssertionError(f"Unexpected SQL: {statement}")
        return type("Result", (), {"fetchone": staticmethod(lambda: value)})()


class PostgresApplicationRoleSecurityTests(unittest.TestCase):
    TABLES = ("webp_file_assets", "webp_file_asset_sources", "webp_asset_outbox")

    def test_scoped_role_with_crud_on_catalog_tables_is_allowed(self):
        connection = FakeConnection(tables={
            f"public.{table}": (True, True) for table in self.TABLES
        })
        assert_postgres_application_role(
            connection, schema="public", tables=self.TABLES
        )

    def test_each_direct_administrative_capability_is_rejected(self):
        for index in range(5):
            flags = [False] * 5
            flags[index] = True
            with self.subTest(flag=index):
                connection = FakeConnection(
                    role=tuple(flags),
                    tables={f"public.{table}": (True, True) for table in self.TABLES},
                )
                with self.assertRaisesRegex(PostgresRoleError, "صلاحيات مدير"):
                    assert_postgres_application_role(
                        connection, schema="public", tables=self.TABLES
                    )

    def test_membership_in_elevated_role_is_rejected(self):
        connection = FakeConnection(
            elevated=("pg_write_all_data",),
            tables={f"public.{table}": (True, True) for table in self.TABLES},
        )
        with self.assertRaisesRegex(PostgresRoleError, "عضو في دور"):
            assert_postgres_application_role(
                connection, schema="public", tables=self.TABLES
            )

    def test_missing_connect_or_schema_usage_is_rejected(self):
        for access in ((False, True, True), (True, False, True)):
            with self.subTest(access=access):
                connection = FakeConnection(access=access)
                with self.assertRaisesRegex(PostgresRoleError, "CONNECT|USAGE"):
                    assert_postgres_application_role(connection, schema="public")

    def test_schema_create_is_required_only_for_explicit_initialization(self):
        connection = FakeConnection(
            access=(True, True, False),
            tables={f"public.{table}": (True, True) for table in self.TABLES},
        )
        assert_postgres_application_role(
            connection, schema="public", tables=self.TABLES,
            require_schema_create=False,
        )
        with self.assertRaisesRegex(PostgresRoleError, "يلزم CREATE"):
            assert_postgres_application_role(
                connection, schema="public", tables=self.TABLES,
                require_schema_create=True,
            )

    def test_missing_tables_are_allowed_only_during_initialization(self):
        connection = FakeConnection(access=(True, True, True))
        assert_postgres_application_role(
            connection, schema="public", tables=self.TABLES,
            require_schema_create=True,
        )
        with self.assertRaisesRegex(PostgresRoleError, "CRUD"):
            assert_postgres_application_role(
                connection, schema="public", tables=self.TABLES,
                require_schema_create=False,
            )

    def test_missing_crud_on_existing_table_is_rejected(self):
        connection = FakeConnection(
            tables={"public.webp_file_assets": (True, False)}
        )
        with self.assertRaisesRegex(PostgresRoleError, "CRUD"):
            assert_postgres_application_role(
                connection, schema="public", tables=("webp_file_assets",),
                require_schema_create=True,
            )


if __name__ == "__main__":
    unittest.main()
