"""الاتصال بخادم FTP/FTPS.

لا نفترض أن FTP وFTPS متبادلان: في الوضع auto نفحص دعم AUTH TLS أولًا،
ولا نرجع إلى FTP غير المشفر إلا إذا سمح المستخدم صراحة. أخطاء الشهادة
لا تؤدي أبدًا إلى خفض مستوى الأمان. كلمة المرور لا تُسجَّل.
"""
from __future__ import annotations

import ftplib
import logging
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Callable

from .config import AppConfig
from .logging_setup import register_secret

log = logging.getLogger(__name__)


def _ssl_reason(exc: ssl.SSLError) -> str:
    return (getattr(exc, "verify_message", None) or getattr(exc, "reason", None)
            or (exc.args[-1] if exc.args else "") or type(exc).__name__)


class FtpError(Exception):
    kind = "error"


class AuthenticationError(FtpError):
    kind = "auth"


class NetworkError(FtpError):
    kind = "network"


class TlsError(FtpError):
    kind = "tls"


class PlainFtpNotAllowedError(FtpError):
    kind = "plain_not_allowed"


@dataclass(frozen=True)
class ConnectionSettings:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    passive: bool = True
    protocol: str = "auto"
    allow_plain_ftp: bool = False
    timeout: int = 30
    max_retries: int = 4

    @classmethod
    def from_config(cls, cfg: AppConfig, password: str) -> "ConnectionSettings":
        return cls(cfg.host.strip(), int(cfg.port), cfg.username.strip(), password,
                   cfg.passive, cfg.protocol, cfg.allow_plain_ftp,
                   int(cfg.timeout_seconds), int(cfg.max_retries))


def default_ftp_factory(use_tls: bool, timeout: int):
    if use_tls:
        return ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=timeout)
    return ftplib.FTP(timeout=timeout)


FtpFactory = Callable[[bool, int], object]


class FtpSession:
    def __init__(self, ftp, use_tls: bool, greeting: str):
        self.ftp = ftp
        self.use_tls = use_tls
        self.greeting = greeting

    @property
    def protocol_label(self) -> str:
        return "FTPS (TLS صريح)" if self.use_tls else "FTP عادي (غير مشفّر)"

    def close(self) -> None:
        try:
            self.ftp.quit()
        except Exception:
            try:
                self.ftp.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _supports_tls(settings: ConnectionSettings, factory: FtpFactory) -> bool:
    """يفحص AUTH TLS قبل إرسال أي كلمة مرور."""
    ftp = factory(True, settings.timeout)
    try:
        ftp.connect(settings.host, settings.port, settings.timeout)
        ftp.auth()
        return True
    except ssl.SSLCertVerificationError as exc:
        raise TlsError(f"فشل التحقق من شهادة الخادم: {_ssl_reason(exc)}") from exc
    except (ftplib.error_perm, ftplib.error_reply, ftplib.error_proto):
        return False  # الخادم رفض AUTH TLS صراحة
    finally:
        try:
            ftp.close()
        except Exception:
            pass


def _connect_once(settings: ConnectionSettings, use_tls: bool, factory: FtpFactory) -> FtpSession:
    ftp = factory(use_tls, settings.timeout)
    try:
        ftp.encoding = "utf-8"
        greeting = ftp.connect(settings.host, settings.port, settings.timeout)
        if use_tls:
            ftp.auth()
        ftp.login(settings.username, settings.password)
        if use_tls:
            ftp.prot_p()
        ftp.set_pasv(settings.passive)
        return FtpSession(ftp, use_tls, str(greeting))
    except BaseException:
        try:
            ftp.close()
        except Exception:
            pass
        raise


def _with_retries(fn, settings: ConnectionSettings, sleep: Callable[[float], None]):
    last: Exception | None = None
    for attempt in range(1, settings.max_retries + 1):
        try:
            return fn()
        except ssl.SSLCertVerificationError as exc:
            raise TlsError(f"فشل التحقق من شهادة الخادم: {_ssl_reason(exc)}") from exc
        except ssl.SSLError as exc:
            raise TlsError(f"خطأ TLS: {exc}") from exc
        except ftplib.error_perm as exc:
            if str(exc).startswith("530"):
                raise AuthenticationError(str(exc)) from exc  # لا نعيد المحاولة: تجنّبًا لقفل الحساب
            raise FtpError(str(exc)) from exc
        except (ftplib.error_temp, OSError, EOFError, ftplib.error_reply) as exc:
            last = exc
            if attempt < settings.max_retries:
                delay = min(2.0 ** (attempt - 1), 30.0)
                log.warning("فشلت المحاولة %d/%d (%s). إعادة المحاولة بعد %.0f ثانية",
                            attempt, settings.max_retries, type(exc).__name__, delay)
                sleep(delay)
    raise NetworkError(f"تعذّر الاتصال بعد {settings.max_retries} محاولات: {last}") from last


def open_session(settings: ConnectionSettings, factory: FtpFactory = default_ftp_factory,
                 sleep: Callable[[float], None] = time.sleep) -> FtpSession:
    register_secret(settings.password)
    if settings.protocol == "ftps":
        use_tls = True
    elif settings.protocol == "ftp":
        use_tls = False
    else:  # auto
        use_tls = _with_retries(lambda: _supports_tls(settings, factory), settings, sleep)
        if not use_tls and not settings.allow_plain_ftp:
            raise PlainFtpNotAllowedError(
                "الخادم لا يدعم TLS الصريح، والرجوع إلى FTP غير المشفر غير مسموح.")
    log.info("فتح اتصال: %s:%s عبر %s", settings.host, settings.port, "FTPS" if use_tls else "FTP")
    return _with_retries(lambda: _connect_once(settings, use_tls, factory), settings, sleep)


@dataclass
class ConnectionTestResult:
    ok: bool
    message_ar: str
    kind: str = ""
    protocol: str = ""
    greeting: str = ""
    cwd: str = ""


_MESSAGES = {
    "auth": "فشل تسجيل الدخول. تأكد من اسم المستخدم (wmo_xx) وكلمة مرور FTP الخاصة بمجموعة WMO Support، "
            "فهي ليست كلمة مرور موقع ECMWF.",
    "network": "تعذّر الوصول إلى الخادم. تحقق من الإنترنت والمضيف والمنفذ وجدار الحماية ووضع Passive.",
    "tls": "فشل إنشاء اتصال TLS آمن.",
    "plain_not_allowed": "الخادم لا يدعم FTPS. لن يُرسل البرنامج كلمة المرور بدون تشفير إلا إذا اخترت "
                         "«FTP عادي» أو فعّلت السماح به صراحة.",
}


def test_connection(settings: ConnectionSettings, factory: FtpFactory = default_ftp_factory,
                    sleep: Callable[[float], None] = time.sleep) -> ConnectionTestResult:
    """لا ترفع استثناءات؛ تعيد نتيجة مقروءة."""
    try:
        with open_session(settings, factory, sleep) as session:
            try:
                cwd = session.ftp.pwd()
            except Exception:
                cwd = ""
            return ConnectionTestResult(True, "تم الاتصال وتسجيل الدخول بنجاح.", "", session.protocol_label,
                                        session.greeting, cwd)
    except FtpError as exc:
        base = _MESSAGES.get(exc.kind, "حدث خطأ في الاتصال.")
        log.error("فشل اختبار الاتصال [%s]: %s", exc.kind, exc)
        return ConnectionTestResult(False, f"{base}\nالتفاصيل: {exc}", exc.kind)
    except Exception as exc:  # خطأ غير متوقع
        log.exception("خطأ غير متوقع أثناء اختبار الاتصال")
        return ConnectionTestResult(False, f"خطأ غير متوقع: {type(exc).__name__}", "unexpected")
