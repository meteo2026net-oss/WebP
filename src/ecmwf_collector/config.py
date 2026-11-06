"""إعدادات البرنامج. لا تحتوي أبدًا على كلمة مرور."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

PROTOCOLS = ("auto", "ftps", "ftp")
KINDS = ("AN", "FM", "FP", "FS")
CYCLES = ("00", "06", "12", "18")


def resource_root() -> Path:
    """Read-only application resources (source checkout or PyInstaller bundle)."""
    import sys
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[2]


def project_root() -> Path:
    """Writable per-user data directory in frozen builds; repository root in source mode."""
    import sys
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "ECMWFWebP"
    return Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    pass


@dataclass
class AppConfig:
    host: str = "diss.ecmwf.int"
    port: int = 21
    username: str = ""
    passive: bool = True
    protocol: str = "auto"          # auto | ftps | ftp
    allow_plain_ftp: bool = False   # يسمح بالرجوع إلى FTP غير مشفر في الوضع auto
    timeout_seconds: int = 30
    max_retries: int = 4
    download_root: str = "downloads"
    remember_password: bool = False  # الحفظ في keyring فقط
    selected_kinds: list = field(default_factory=lambda: list(KINDS))
    selected_cycles: list = field(default_factory=lambda: list(CYCLES))
    max_parallel: int = 1            # اتصالات تنزيل متزامنة (متحفظ)
    min_free_gb: int = 5             # الحد الأدنى للمساحة الحرة المتروكة على القرص

    @staticmethod
    def _integer(value, field_name: str) -> int:
        # bool is an int subclass in Python, but accepting True as port=1 is unsafe.
        if isinstance(value, bool):
            raise ConfigError(f"قيمة {field_name} يجب أن تكون رقماً صحيحاً")
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ConfigError(f"قيمة {field_name} غير صحيحة") from exc

    def validate(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise ConfigError("المضيف مطلوب")
        port = self._integer(self.port, "المنفذ")
        timeout = self._integer(self.timeout_seconds, "المهلة")
        retries = self._integer(self.max_retries, "عدد المحاولات")
        parallel = self._integer(self.max_parallel, "التنزيلات المتزامنة")
        free_gb = self._integer(self.min_free_gb, "المساحة الحرة الدنيا")
        if not (1 <= port <= 65535):
            raise ConfigError("المنفذ يجب أن يكون بين 1 و65535")
        if not isinstance(self.protocol, str) or self.protocol not in PROTOCOLS:
            raise ConfigError(f"بروتوكول غير معروف: {self.protocol}")
        if timeout <= 0:
            raise ConfigError("المهلة يجب أن تكون أكبر من صفر")
        if not (1 <= retries <= 10):
            raise ConfigError("عدد المحاولات يجب أن يكون بين 1 و10")
        if not (1 <= parallel <= 3):
            raise ConfigError("التنزيلات المتزامنة يجب أن تكون بين 1 و3")
        if free_gb < 0:
            raise ConfigError("المساحة الحرة الدنيا لا يمكن أن تكون سالبة")
        if (not isinstance(self.selected_kinds, list)
                or not all(isinstance(v, str) for v in self.selected_kinds)
                or not isinstance(self.selected_cycles, list)
                or not all(isinstance(v, str) for v in self.selected_cycles)):
            raise ConfigError("قوائم أنواع الملفات وأوقات الإصدار يجب أن تكون قوائم نصية")
        if not set(self.selected_kinds) <= set(KINDS) or not set(self.selected_cycles) <= set(CYCLES):
            raise ConfigError("أنواع الملفات أو أوقات الإصدار غير صحيحة")


def load_config(path: Path) -> AppConfig:
    path = Path(path)
    if not path.exists():
        return AppConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"تعذّرت قراءة ملف الإعدادات: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("صيغة ملف الإعدادات غير صحيحة")
    known = {f.name for f in fields(AppConfig)}
    cfg = AppConfig(**{k: v for k, v in raw.items() if k in known})
    cfg.validate()
    return cfg


def save_config(cfg: AppConfig, path: Path) -> None:
    """كتابة ذرّية. الحقول مأخوذة من dataclass فقط فلا يمكن أن تتسرب كلمة مرور."""
    cfg.validate()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(cfg), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
