"""Shared database connection helpers for optional MySQL/MariaDB backends."""
from __future__ import annotations

from pathlib import Path


class DatabaseDriverError(RuntimeError):
    """A database driver could not be initialized safely."""



# Privileges that turn an application login into a server-level administrator
# or grant access to server files / account management. Schema-scoped CRUD
# grants remain valid for the explicitly selected application database.
_ALLOWED_APPLICATION_PRIVILEGES = {"SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "REFERENCES"}


def assert_mysql_application_role(connection, database: str) -> None:
    """Require only CRUD plus approved catalog-table creation, scoped to the selected database."""
    with connection.cursor() as cursor:
        cursor.execute("SHOW GRANTS")
        grants = cursor.fetchall()
    if not grants:
        raise DatabaseDriverError("تعذّر التحقق من صلاحيات حساب MySQL/MariaDB.")

    expected_database = database.replace("`", "").strip().lower()
    if not expected_database:
        raise DatabaseDriverError("اسم قاعدة البيانات المطلوبة للتحقق من الصلاحيات غير صالح.")

    for row in grants:
        statement = str(row[0] if isinstance(row, (tuple, list)) else row).strip().rstrip(";")
        normalized = statement.upper().replace("`", "")
        if not normalized.startswith("GRANT "):
            raise DatabaseDriverError("تعذّر تفسير منح صلاحيات حساب MySQL/MariaDB.")
        if " ON " not in normalized:
            # Role memberships and proxy grants are not accepted for this
            # dedicated application login. Plain USAGE is represented with ON *.*.
            raise DatabaseDriverError("حساب MySQL/MariaDB مرتبط بدور أو امتياز غير مسموح.")
        privilege_clause, scope_clause = normalized[6:].split(" ON ", 1)
        if " TO " not in scope_clause:
            raise DatabaseDriverError("تعذّر تفسير نطاق صلاحيات حساب MySQL/MariaDB.")
        scope = scope_clause.split(" TO ", 1)[0].strip().lower()
        privileges = {part.strip() for part in privilege_clause.split(",")}
        if privileges == {"USAGE"} and scope == "*.*":
            continue
        if not privileges or not privileges.issubset(_ALLOWED_APPLICATION_PRIVILEGES):
            raise DatabaseDriverError(
                "حساب MySQL/MariaDB يمتلك صلاحيات تتجاوز CRUD المسموح لحساب التطبيق."
            )
        if scope == "*.*" or not (
            scope == f"{expected_database}.*"
            or scope.startswith(f"{expected_database}.")
        ):
            raise DatabaseDriverError(
                "حساب MySQL/MariaDB يمتلك صلاحيات خارج قاعدة البيانات المحددة."
            )


def open_mysql_connection(profile, secrets, timeout: int = 5):
    """Open a bounded-time MySQL/MariaDB connection using the OS secret vault.

    SSL verification modes require an explicit CA file. prefer and require
    request TLS without certificate verification; disable explicitly disables
    TLS. No SQL writes or schema changes are performed.
    """
    if profile.backend not in {"mysql", "mariadb"}:
        raise DatabaseDriverError("ملف الاتصال ليس MySQL/MariaDB.")
    password = secrets.get_password(profile.credential_key) if secrets else None
    if not password:
        raise DatabaseDriverError("كلمة مرور الاتصال غير موجودة في مخزن أسرار النظام.")

    try:
        import pymysql
    except ImportError as exc:
        raise ImportError("موصل MySQL/MariaDB PyMySQL غير مثبت.") from exc

    options = {}
    if profile.ssl_mode == "disable":
        options["ssl_disabled"] = True
    elif profile.ssl_mode in {"verify-ca", "verify-full"}:
        ca_file = Path(profile.ssl_ca).expanduser()
        if not ca_file.is_file():
            raise DatabaseDriverError("ملف شهادة CA المحدد غير موجود.")
        import ssl
        options["ssl"] = {
            "ca": str(ca_file),
            "verify_mode": ssl.CERT_REQUIRED,
            "check_hostname": profile.ssl_mode == "verify-full",
        }
    else:
        # PyMySQL has no libpq-style opportunistic TLS negotiation.
        # Both modes request an encrypted channel without certificate verification.
        options["ssl"] = {}

    return pymysql.connect(
        host=profile.host,
        port=profile.port,
        database=profile.database,
        user=profile.username,
        password=password,
        connect_timeout=timeout,
        read_timeout=timeout,
        write_timeout=timeout,
        charset="utf8mb4",
        autocommit=True,
        **options,
    )
