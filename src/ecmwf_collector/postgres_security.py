"""Least-privilege checks for PostgreSQL application connections."""
from __future__ import annotations

import re


class PostgresRoleError(RuntimeError):
    """A PostgreSQL login exceeds the application's database privilege boundary."""


_ELEVATED_ROLE_NAMES = frozenset({
    "pg_read_all_data", "pg_write_all_data", "pg_execute_server_program",
    "pg_read_server_files", "pg_write_server_files", "pg_monitor",
    "pg_read_all_settings", "pg_read_all_stats", "pg_signal_backend",
})
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def assert_postgres_application_role(
    connection,
    *,
    schema: str = "public",
    tables: tuple[str, ...] = (),
    require_schema_create: bool = False,
) -> None:
    """Reject administrative roles and require only scoped schema/table access.

    Schema CREATE is checked only during explicit catalogue initialization.
    Normal catalogue operations require CONNECT, schema USAGE, and CRUD on
    every catalogue table. Missing tables are tolerated only during explicit
    initialization, where the caller must also possess schema CREATE.
    """
    if not isinstance(schema, str) or not _IDENTIFIER.fullmatch(schema):
        raise PostgresRoleError("اسم مخطط PostgreSQL غير صالح.")
    if any(not isinstance(table, str) or not _IDENTIFIER.fullmatch(table) for table in tables):
        raise PostgresRoleError("اسم جدول PostgreSQL غير صالح.")

    role = connection.execute(
        """
        SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
        FROM pg_roles WHERE rolname = current_user
        """
    ).fetchone()
    if role is None:
        raise PostgresRoleError("تعذّر التحقق من صلاحيات حساب PostgreSQL الحالي.")
    if any(bool(flag) for flag in role):
        raise PostgresRoleError(
            "رفض الاتصال: حساب PostgreSQL يجب ألا يملك صلاحيات مدير أو إنشاء قواعد/أدوار أو تجاوز RLS."
        )

    elevated = connection.execute(
        """
        SELECT r.rolname
        FROM pg_roles AS r
        WHERE r.oid <> current_user::regrole::oid
          AND (
            r.rolsuper OR r.rolcreatedb OR r.rolcreaterole
            OR r.rolreplication OR r.rolbypassrls
            OR r.rolname = ANY(%s)
          )
          AND pg_has_role(current_user, r.oid, 'MEMBER')
        LIMIT 1
        """,
        (list(_ELEVATED_ROLE_NAMES),),
    ).fetchone()
    if elevated:
        raise PostgresRoleError(
            "رفض الاتصال: حساب PostgreSQL عضو في دور ذي صلاحيات مرتفعة."
        )

    access = connection.execute(
        """
        SELECT has_database_privilege(current_user, current_database(), 'CONNECT'),
               has_schema_privilege(current_user, %s, 'USAGE'),
               has_schema_privilege(current_user, %s, 'CREATE')
        """,
        (schema, schema),
    ).fetchone()
    if access is None or not bool(access[0]) or not bool(access[1]):
        raise PostgresRoleError(
            "رفض الاتصال: حساب PostgreSQL يفتقد CONNECT لقاعدة البيانات أو USAGE للمخطط."
        )
    if require_schema_create and not bool(access[2]):
        raise PostgresRoleError(
            "رفض تهيئة كتالوج PostgreSQL: يلزم CREATE على المخطط المحدد."
        )

    for table in tables:
        qualified = f"{schema}.{table}"
        privileges = connection.execute(
            """
            SELECT to_regclass(%s) IS NOT NULL,
                   CASE WHEN to_regclass(%s) IS NULL THEN FALSE ELSE
                     has_table_privilege(current_user, to_regclass(%s), 'SELECT')
                     AND has_table_privilege(current_user, to_regclass(%s), 'INSERT')
                     AND has_table_privilege(current_user, to_regclass(%s), 'UPDATE')
                     AND has_table_privilege(current_user, to_regclass(%s), 'DELETE')
                   END
            """,
            (qualified, qualified, qualified, qualified, qualified, qualified),
        ).fetchone()
        exists, has_crud = bool(privileges[0]), bool(privileges[1])
        if not exists and require_schema_create:
            continue
        if not exists or not has_crud:
            raise PostgresRoleError(
                f"رفض الاتصال: حساب PostgreSQL يفتقد صلاحيات CRUD على الجدول {qualified}."
            )
