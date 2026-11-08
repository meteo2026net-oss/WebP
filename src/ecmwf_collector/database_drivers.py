"""Shared database connection helpers for optional MySQL/MariaDB backends."""
from __future__ import annotations

from pathlib import Path


class DatabaseDriverError(RuntimeError):
    """A database driver could not be initialized safely."""


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
