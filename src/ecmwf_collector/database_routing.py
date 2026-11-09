"""Explicit per-model database routing metadata.

Routes only choose a registered connection profile. They never contain credentials,
and they do not move or replicate data.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


class DatabaseRoutingError(ValueError):
    pass


class DatabaseRoutingStore:
    VERSION = 1

    def __init__(self, path: Path, profile_store):
        self.path = Path(path)
        self.profile_store = profile_store
        self._routes: dict[str, str] = {}
        self._default_profile_id: str | None = None
        self.load()

    @staticmethod
    def model_key(provider: str, model: str, product: str = "default") -> str:
        parts = (provider.strip(), model.strip(), product.strip())
        if not all(parts):
            raise DatabaseRoutingError("المزوّد والنموذج والمنتج مطلوبة لتحديد مسار البيانات.")
        return "::".join(part.casefold() for part in parts)

    def load(self) -> None:
        if not self.path.exists():
            self._routes, self._default_profile_id = {}, None
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DatabaseRoutingError("تعذّرت قراءة إعدادات توجيه قواعد البيانات.") from exc
        if not isinstance(payload, dict) or payload.get("version") != self.VERSION:
            raise DatabaseRoutingError("إصدار إعدادات توجيه قواعد البيانات غير معروف.")
        routes = payload.get("routes", {})
        default_id = payload.get("default_profile_id")
        if not isinstance(routes, dict) or any(
            not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip()
            for k, v in routes.items()
        ):
            raise DatabaseRoutingError("جدول توجيه النماذج غير صالح.")
        if default_id is not None and not isinstance(default_id, str):
            raise DatabaseRoutingError("قاعدة البيانات الافتراضية غير صالحة.")
        self._routes = dict(routes)
        self._default_profile_id = default_id

    def set_route(self, model_key: str, profile_id: str) -> None:
        self._validate_model_key(model_key)
        self._require_enabled_profile(profile_id)
        self._routes[model_key] = profile_id
        self._write()

    def clear_route(self, model_key: str) -> bool:
        if model_key not in self._routes:
            return False
        del self._routes[model_key]
        self._write()
        return True

    def set_default(self, profile_id: str | None) -> None:
        if profile_id is not None:
            self._require_enabled_profile(profile_id)
        self._default_profile_id = profile_id
        self._write()

    def resolve(self, model_key: str) -> str | None:
        self._validate_model_key(model_key)
        profile_id = self._routes.get(model_key, self._default_profile_id)
        if profile_id is None:
            return None
        profile = self.profile_store.get(profile_id)
        if profile is None or not profile.enabled:
            raise DatabaseRoutingError(
                f"الاتصال المحدد للنموذج {model_key} غير موجود أو معطّل؛ لم يتم تحويل البيانات إلى اتصال آخر."
            )
        return profile_id

    def remove_profile_references(self, profile_id: str) -> int:
        """Explicitly clear routes before a profile is deleted; never silently reroute."""
        before = len(self._routes)
        self._routes = {key: value for key, value in self._routes.items() if value != profile_id}
        removed = before - len(self._routes)
        if self._default_profile_id == profile_id:
            self._default_profile_id = None
            removed += 1
        if removed:
            self._write()
        return removed

    def snapshot(self) -> dict:
        return {
            "default_profile_id": self._default_profile_id,
            "routes": dict(sorted(self._routes.items())),
        }

    @staticmethod
    def _validate_model_key(model_key: str) -> None:
        if not isinstance(model_key, str) or not model_key.strip():
            raise DatabaseRoutingError("مفتاح النموذج مطلوب.")

    def _require_enabled_profile(self, profile_id: str) -> None:
        profile = self.profile_store.get(profile_id)
        if profile is None:
            raise DatabaseRoutingError("ملف اتصال قاعدة البيانات غير موجود.")
        if not profile.enabled:
            raise DatabaseRoutingError("لا يمكن توجيه نموذج إلى اتصال معطّل.")

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": self.VERSION, **self.snapshot()}
        fd, temporary = tempfile.mkstemp(prefix="db-routing-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise
