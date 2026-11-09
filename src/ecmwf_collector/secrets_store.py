"""تخزين كلمة المرور في مخزن أسرار نظام التشغيل (Windows Credential Manager)."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)
SERVICE = "ECMWF_Data_Collector"
POSTGRES_DSN_KEY = "postgresql_dsn"


class SecretStore:
    def __init__(self, backend=None):
        self._backend = backend
        self._injected_backend = backend is not None
        if backend is None:
            try:
                import keyring  # type: ignore
                self._backend = keyring
            except Exception:  # المكتبة غير مثبتة
                self._backend = None

    @property
    def available(self) -> bool:
        if self._backend is None:
            return False
        # Explicitly injected adapters are used by isolated tests. Production
        # keyring selection must resolve to an OS credential-vault backend;
        # keyrings.alt plaintext/file backends are deliberately rejected.
        if self._injected_backend:
            return True
        try:
            backend = self._backend.get_keyring()
            module = type(backend).__module__
            secure_modules = (
                "keyring.backends.Windows",
                "keyring.backends.macOS",
                "keyring.backends.SecretService",
                "keyring.backends.kwallet",
            )
            return (
                float(getattr(backend, "priority", 0)) > 0
                and any(module == prefix or module.startswith(prefix + ".")
                        for prefix in secure_modules)
            )
        except Exception:
            return False

    def get_password(self, username: str) -> str | None:
        if not self.available or not username:
            return None
        try:
            return self._backend.get_password(SERVICE, username)
        except Exception as exc:
            log.warning("تعذّرت قراءة مخزن الأسرار: %s", type(exc).__name__)
            return None

    def set_password(self, username: str, password: str) -> bool:
        if not self.available or not username or not password:
            return False
        try:
            self._backend.set_password(SERVICE, username, password)
            return True
        except Exception as exc:
            log.warning("تعذّر الحفظ في مخزن الأسرار: %s", type(exc).__name__)
            return False

    def get_postgres_dsn(self) -> str | None:
        """Read the local PostgreSQL DSN from the OS credential vault."""
        return self.get_password(POSTGRES_DSN_KEY)

    def set_postgres_dsn(self, dsn: str) -> bool:
        """Store the PostgreSQL DSN (including any password) in the OS credential vault."""
        return self.set_password(POSTGRES_DSN_KEY, dsn)

    def delete_postgres_dsn(self) -> bool:
        return self.delete_password(POSTGRES_DSN_KEY)

    def delete_password(self, username: str) -> bool:
        if not self.available or not username:
            return False
        try:
            self._backend.delete_password(SERVICE, username)
            return True
        except Exception:
            return False
