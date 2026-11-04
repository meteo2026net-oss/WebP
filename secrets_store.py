"""تخزين كلمة المرور في مخزن أسرار نظام التشغيل (Windows Credential Manager)."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)
SERVICE = "ECMWF_Data_Collector"


class SecretStore:
    def __init__(self, backend=None):
        self._backend = backend
        if backend is None:
            try:
                import keyring  # type: ignore
                self._backend = keyring
            except Exception:  # المكتبة غير مثبتة
                self._backend = None

    @property
    def available(self) -> bool:
        return self._backend is not None

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

    def delete_password(self, username: str) -> bool:
        if not self.available or not username:
            return False
        try:
            self._backend.delete_password(SERVICE, username)
            return True
        except Exception:
            return False
