"""Create a least-privilege PostgreSQL login for the desktop application."""
from __future__ import annotations

import secrets

APP_ROLE = "ecmwf_webp_app"


def provision_application_login(admin_dsn: str) -> str:
    """Create a dedicated app login in the database selected by an administrator DSN.

    The administrator DSN is used only for provisioning and is never returned or
    persisted. The generated password is safely SQL-quoted (not passed in process
    arguments) and returned only inside a DSN for the OS credential vault. Server
    statement logging may still record DDL, depending on the server configuration.
    """
    if not admin_dsn or not admin_dsn.strip():
        raise ValueError("أدخل سلسلة اتصال PostgreSQL لحساب المدير.")

    from .logging_setup import register_secret
    register_secret(admin_dsn.strip())

    try:
        import psycopg
        from psycopg import sql
    except ImportError as exc:
        raise RuntimeError("وضع PostgreSQL يتطلب psycopg[binary].") from exc

    app_password = secrets.token_urlsafe(36)
    register_secret(app_password)
    role_created = False
    with psycopg.connect(admin_dsn.strip(), connect_timeout=8) as admin:
        database = admin.execute("SELECT current_database()").fetchone()[0]
        if not database:
            raise RuntimeError("تعذّر تحديد قاعدة البيانات الحالية.")
        exists = admin.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,)
        ).fetchone()
        if exists:
            raise RuntimeError(
                f"الحساب {APP_ROLE} موجود مسبقاً؛ أوقف الإعداد لتجنب تغيير بيانات اعتماد موجودة."
            )
        with admin.transaction():
            admin.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(
                    sql.Identifier(APP_ROLE), sql.Literal(app_password)
                )
            )
            role_created = True
            admin.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO ecmwf_webp_app").format(
                    sql.Identifier(database)
                )
            )
            admin.execute("GRANT USAGE, CREATE ON SCHEMA public TO ecmwf_webp_app")

    app_dsn = psycopg.conninfo.make_conninfo(
        admin_dsn.strip(), user=APP_ROLE, password=app_password
    )
    register_secret(app_dsn)
    store = None
    try:
        from .postgres_state import PostgresStateStore
        store = PostgresStateStore(app_dsn)
        return app_dsn
    except Exception as exc:
        # Remove the newly-created role if the app login cannot initialize.
        if role_created:
            try:
                with psycopg.connect(admin_dsn.strip(), connect_timeout=8) as admin:
                    database = admin.execute("SELECT current_database()").fetchone()[0]
                    from psycopg import sql
                    admin.execute(
                        sql.SQL("REVOKE CONNECT ON DATABASE {} FROM ecmwf_webp_app").format(
                            sql.Identifier(database)
                        )
                    )
                    admin.execute("REVOKE ALL ON SCHEMA public FROM ecmwf_webp_app")
                    admin.execute("DROP ROLE IF EXISTS ecmwf_webp_app")
            except Exception:
                pass
        raise RuntimeError(
            f"تعذّر تهيئة حساب PostgreSQL للتطبيق ({type(exc).__name__})."
        ) from None
    finally:
        if store is not None:
            store.close()
