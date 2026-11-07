"""Create a least-privilege PostgreSQL login for the desktop application."""
from __future__ import annotations

import secrets

APP_ROLE = "ecmwf_webp_app"


def remove_new_application_login(admin_dsn: str) -> None:
    """Remove only the dedicated app role created by this setup attempt.

    The administrator-owned public.files table and every row are deliberately
    retained. Call only when the caller knows this attempt created the role.
    """
    if not admin_dsn or not admin_dsn.strip():
        raise ValueError("أدخل سلسلة اتصال PostgreSQL لحساب المدير.")
    try:
        import psycopg
        from psycopg import sql
    except ImportError as exc:
        raise RuntimeError("وضع PostgreSQL يتطلب psycopg[binary].") from exc

    with psycopg.connect(admin_dsn.strip(), connect_timeout=8) as admin:
        database = admin.execute("SELECT current_database()").fetchone()[0]
        admin.execute(
            sql.SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
                sql.Identifier(database), sql.Identifier(APP_ROLE)
            )
        )
        admin.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ON TABLE public.files FROM {}").format(
                sql.Identifier(APP_ROLE)
            )
        )
        admin.execute(
            sql.SQL("REVOKE ALL PRIVILEGES ON SCHEMA public FROM {}").format(
                sql.Identifier(APP_ROLE)
            )
        )
        admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(APP_ROLE)))


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
    from .postgres_state import CREATE_TABLE
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
            # Create the table as the administrator so the application login
            # never needs CREATE on the shared public schema.
            admin.execute(CREATE_TABLE)
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
            admin.execute("GRANT USAGE ON SCHEMA public TO ecmwf_webp_app")
            admin.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.files TO ecmwf_webp_app"
            )

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
                remove_new_application_login(admin_dsn)
            except Exception:
                pass
        raise RuntimeError(
            f"تعذّر تهيئة حساب PostgreSQL للتطبيق ({type(exc).__name__})."
        ) from None
    finally:
        if store is not None:
            store.close()
