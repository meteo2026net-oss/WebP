"""Shared database connection helpers for optional MySQL/MariaDB backends."""
from __future__ import annotations

from pathlib import Path


class DatabaseDriverError(RuntimeError):
    """A database driver could not be initialized safely."""



# Privileges that turn an application login into a server-level administrator
# or grant access to server files / account management. Schema-scoped CRUD
# grants remain valid for the explicitly selected application database.
_FORBIDDEN_GLOBAL_PRIVILEGES = {
    "ALL PRIVILEGES", "SUPER", "FILE", "PROCESS", "RELOAD", "SHUTDOWN",
    "CREATE USER", "GRANT OPTION", "SYSTEM_USER", "SYSTEM_VARIABLES_ADMIN",
    "CONNECTION_ADMIN", "ROLE_ADMIN", "BINLOG_ADMIN", "REPLICATION_SLAVE_ADMIN",
    "REPLICATION_APPLIER", "PERSIST_RO_VARIABLES_ADMIN", "SET_USER_ID",
}


def assert_mysql_application_role(connection) -> None:
    """Reject global/admin grants before treating a MySQL login as an app role."""
    with connection.cursor() as cursor:
        cursor.execute("SHOW GRANTS")
        grants = cursor.fetchall()
    if not grants:
        raise DatabaseDriverError("تعذّر التحقق من صلاحيات حساب MySQL/MariaDB.")
    for row in grants:
        statement = str(row[0] if isinstance(row, (tuple, list)) else row).upper()
        if " ON *.* " not in f" {statement} ":
            continue
        privilege_clause = statement.split(" ON *.* ", 1)[0]
        for privilege in _FORBIDDEN_GLOBAL_PRIVILEGES:
            if privilege in privilege_clause:
                raise DatabaseDriverError(
                    "حساب MySQL/MariaDB يمتلك امتيازاً عاماً أو إدارياً غير مناسب لحساب التطبيق."
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
