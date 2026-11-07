"""Arabic forecaster review console with browser-based OIDC PKCE login.

The desktop client is a public OAuth client: no client secret, no refresh-token
persistence, and access tokens exist only in process memory.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, urlencode

import requests
from authlib.integrations.requests_client import OAuth2Session
from authlib.oidc.core import CodeIDToken
from joserfc import jwt
from joserfc.jwk import KeySet
from joserfc.jws import JWSRegistry
from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPushButton, QPlainTextEdit, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView,
)

_LOG = logging.getLogger(__name__)


class ReviewAuthError(RuntimeError):
    pass


class OidcPkceLogin:
    """Interactive OIDC Authorization Code + PKCE; no client secret/refresh token."""

    def __init__(self, issuer: str, client_id: str, scopes: str = "openid profile"):
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id.strip()
        self.scopes = scopes

    @staticmethod
    def _callback_server():
        received = {}
        ready = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/oidc/callback":
                    self.send_error(404)
                    return
                received.update(parse_qs(parsed.query))
                body = (
                    b"<!doctype html><meta charset=utf-8><title>Weather review</title>"
                    b"<p>Authentication response received. You may return to the app.</p>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                ready.set()

            def log_message(self, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        server.timeout = 1
        redirect_uri = f"http://127.0.0.1:{server.server_port}/oidc/callback"
        return server, received, ready, redirect_uri

    def login(self, timeout_seconds: int = 180) -> tuple[str, int]:
        if not self.issuer.startswith("https://") or not self.client_id:
            raise ReviewAuthError("أدخل عنوان OIDC آمن (HTTPS) ومعرّف التطبيق العام")
        discovery_url = self.issuer + "/.well-known/openid-configuration"
        try:
            discovery = requests.get(discovery_url, timeout=10)
            discovery.raise_for_status()
            metadata = discovery.json()
        except Exception as exc:
            raise ReviewAuthError(f"تعذر تحميل إعدادات OIDC: {exc}") from exc
        for key in ("issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not isinstance(metadata.get(key), str) or not metadata[key].startswith("https://"):
                raise ReviewAuthError(f"إعداد OIDC غير صالح: {key}")
        if metadata["issuer"].rstrip("/") != self.issuer:
            raise ReviewAuthError("عنوان issuer لا يطابق عنوان مزود الهوية")

        server, received, ready, redirect_uri = self._callback_server()
        verifier = secrets.token_urlsafe(64)
        nonce = secrets.token_urlsafe(32)
        session = OAuth2Session(
            self.client_id,
            redirect_uri=redirect_uri,
            scope=self.scopes,
            token_endpoint_auth_method="none",
            code_challenge_method="S256",
        )
        auth_url, state = session.create_authorization_url(
            metadata["authorization_endpoint"], nonce=nonce, code_verifier=verifier
        )
        try:
            if not QDesktopServices.openUrl(QUrl(auth_url)):
                raise ReviewAuthError("تعذر فتح متصفح النظام لتسجيل الدخول")
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline and not ready.is_set():
                server.handle_request()
            if not ready.is_set():
                raise ReviewAuthError("انتهت مهلة تسجيل الدخول")
            if received.get("state", [None])[0] != state:
                raise ReviewAuthError("فشل التحقق من state؛ أُلغيت عملية تسجيل الدخول")
            if received.get("error"):
                raise ReviewAuthError("رفض مزود الهوية تسجيل الدخول أو ألغاه")
            callback_url = redirect_uri + "?" + urlencode(
                {key: values[0] for key, values in received.items() if values}
            )
            token = session.fetch_token(
                metadata["token_endpoint"],
                authorization_response=callback_url,
                code_verifier=verifier,
                timeout=15,
            )
            if not token.get("access_token"):
                raise ReviewAuthError("لم يُرجع مزود الهوية رمز وصول")
            if not token.get("id_token"):
                raise ReviewAuthError("استجابة OIDC لا تحتوي على id_token")
            # Validate the ID token signature and OIDC claims explicitly.
            jwks_response = requests.get(metadata["jwks_uri"], timeout=10)
            jwks_response.raise_for_status()
            key_set = KeySet.import_key_set(jwks_response.json())
            id_token = jwt.decode(
                token["id_token"],
                key=key_set,
                registry=JWSRegistry(algorithms=["RS256"], strict_check_header=False),
            )
            claims = CodeIDToken(
                id_token.claims,
                id_token.header,
                {"iss": {"value": metadata["issuer"]}},
                {"nonce": nonce, "client_id": self.client_id,
                 "access_token": token["access_token"]},
            )
            claims.validate(leeway=120)
            if not claims.get("sub"):
                raise ReviewAuthError("تعذر التحقق من هوية المستخدم")
            expires_in = max(1, int(token.get("expires_in", 300)))
            # Explicitly discard tokens that the desktop client must never retain.
            token.pop("refresh_token", None)
            token.pop("id_token", None)
            return str(token["access_token"]), expires_in
        except ReviewAuthError:
            raise
        except Exception as exc:
            raise ReviewAuthError(f"فشل تدفق OIDC/PKCE: {exc}") from exc
        finally:
            server.server_close()


class _TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _TaskSignals()

    def run(self):
        try:
            self.signals.done.emit(self.fn())
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class ReviewApiClient:
    def __init__(self, base_url: str, access_token: str):
        parsed = urlparse(base_url)
        local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
        if parsed.scheme != "https" and not local_http:
            raise ValueError("Review API must use HTTPS outside localhost development")
        if not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Review API URL is invalid")
        self.base_url = base_url.rstrip("/")
        self._access_token = access_token

    def request(self, method: str, path: str, payload=None):
        response = requests.request(
            method,
            self.base_url + path,
            json=payload,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Accept": "application/json",
                "Cache-Control": "no-store",
            },
            timeout=(5, 25),
        )
        if response.status_code == 401:
            raise ReviewAuthError("انتهت صلاحية الجلسة أو رُفض الرمز؛ سجّل الدخول مجدداً")
        if response.status_code == 403:
            raise PermissionError("ليس لديك صلاحية لتنفيذ هذا الإجراء")
        if response.status_code == 409:
            raise RuntimeError("تغيرت الحالة بواسطة مستخدم آخر؛ حدّث قائمة المراجعة")
        if not response.ok:
            try:
                detail = response.json().get("message") or response.json().get("error")
            except Exception:
                detail = response.text[:300]
            raise RuntimeError(f"طلب API فشل ({response.status_code}): {detail}")
        return response.json()

    def clear(self):
        # Python strings cannot be reliably zeroized; drop the only application reference.
        self._access_token = ""


class ReviewConsole(QWidget):
    """Review queue, case timeline, decisions, and publication feed."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("Meteo2026Net", "ECMWFWebP")
        self.pool = QThreadPool(self)
        self.client = None
        self.token_expires_at = 0.0
        self.selected_case = None
        self.queue_items = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        auth = QGroupBox("تسجيل الدخول الآمن — OIDC / PKCE")
        form = QFormLayout(auth)
        self.api_url = QLineEdit(self.settings.value("review/api_url", ""))
        self.issuer = QLineEdit(self.settings.value("review/issuer", ""))
        self.client_id = QLineEdit(self.settings.value("review/client_id", ""))
        for field in (self.api_url, self.issuer, self.client_id):
            field.setLayoutDirection(Qt.LeftToRight)
        form.addRow("عنوان Review API", self.api_url)
        form.addRow("OIDC Issuer", self.issuer)
        form.addRow("Public Client ID", self.client_id)
        buttons = QHBoxLayout()
        self.login_button = QPushButton("تسجيل الدخول عبر المتصفح")
        self.logout_button = QPushButton("إنهاء الجلسة")
        self.refresh_button = QPushButton("تحديث المراجعات")
        self.publish_button = QPushButton("تحديث قائمة النشر")
        self.logout_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.publish_button.setEnabled(False)
        buttons.addWidget(self.login_button)
        buttons.addWidget(self.logout_button)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.publish_button)
        form.addRow(buttons)
        root.addWidget(auth)

        split = QSplitter(Qt.Vertical)
        upper = QWidget()
        upper_layout = QVBoxLayout(upper)
        upper_layout.addWidget(QLabel("قائمة الحالات — اختر حالة لعرض سجلها"))
        self.queue = QTableWidget(0, 7)
        self.queue.setHorizontalHeaderLabels(
            ["Review ID", "Field", "الحالة", "المراجع", "الإصدار", "الجودة", "وقت الصلاحية"]
        )
        self.queue.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.queue.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.queue.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.queue.horizontalHeader().setStretchLastSection(True)
        self.queue.itemSelectionChanged.connect(self._on_case_selected)
        upper_layout.addWidget(self.queue)
        split.addWidget(upper)

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        self.case_title = QLabel("تفاصيل الحالة وسجل التدقيق")
        lower_layout.addWidget(self.case_title)
        self.timeline = QPlainTextEdit()
        self.timeline.setReadOnly(True)
        self.timeline.setMaximumHeight(150)
        lower_layout.addWidget(self.timeline)
        actions = QHBoxLayout()
        self.reviewer_id = QLineEdit()
        self.reviewer_id.setPlaceholderText("معرّف حساب المراجع — للمشرف")
        self.assign_button = QPushButton("إسناد")
        self.open_button = QPushButton("بدء المراجعة")
        self.comment_text = QLineEdit()
        self.comment_text.setPlaceholderText("تعليق المراجع")
        self.comment_button = QPushButton("إضافة تعليق")
        self.decision = QComboBox()
        self.decision.addItem("اعتماد", "approved")
        self.decision.addItem("رفض", "rejected")
        self.decision.addItem("طلب تعديلات", "changes_requested")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("سبب القرار (إلزامي)")
        self.decide_button = QPushButton("تسجيل القرار")
        self.reopen_button = QPushButton("إعادة فتح الحالة")
        for widget in (self.reviewer_id, self.assign_button, self.open_button,
                       self.comment_text, self.comment_button, self.decision,
                       self.reason, self.decide_button, self.reopen_button):
            actions.addWidget(widget)
        lower_layout.addLayout(actions)
        split.addWidget(lower)

        root.addWidget(split, 3)
        root.addWidget(QLabel("الحقول المنشورة — تظهر فقط بعد اجتياز QC والاعتماد البشري"))
        self.published = QTableWidget(0, 5)
        self.published.setHorizontalHeaderLabels(
            ["Field", "وقت الصلاحية", "Forecast hour", "الجودة", "المعرفات"]
        )
        self.published.setEditTriggers(QTableWidget.NoEditTriggers)
        self.published.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.published.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.published, 2)
        self.status = QLabel("غير مسجل الدخول.")
        root.addWidget(self.status)

        self.login_button.clicked.connect(self._login)
        self.logout_button.clicked.connect(self._logout)
        self.refresh_button.clicked.connect(self._refresh_queue)
        self.publish_button.clicked.connect(self._refresh_published)
        self.assign_button.clicked.connect(self._assign)
        self.open_button.clicked.connect(self._open_case)
        self.comment_button.clicked.connect(self._comment)
        self.decide_button.clicked.connect(self._decide)
        self.reopen_button.clicked.connect(self._reopen)

    def _set_busy(self, busy: bool):
        self.login_button.setEnabled(not busy and self.client is None)
        self.refresh_button.setEnabled(not busy and self.client is not None)
        self.publish_button.setEnabled(not busy and self.client is not None)
        self.logout_button.setEnabled(not busy and self.client is not None)
        for button in (self.assign_button, self.open_button, self.comment_button, self.decide_button, self.reopen_button):
            button.setEnabled(not busy and self.client is not None and self.selected_case is not None)

    def _run(self, fn, on_success):
        self._set_busy(True)
        task = _Task(fn)
        task.signals.done.connect(lambda value: (self._set_busy(False), on_success(value)))
        task.signals.failed.connect(lambda error: (self._set_busy(False), self._show_error(error)))
        self.pool.start(task)

    def _show_error(self, error):
        self.status.setText(error)
        if "سجّل الدخول مجدداً" in error:
            self._logout()

    def _login(self):
        api_url = self.api_url.text().strip()
        issuer = self.issuer.text().strip()
        client_id = self.client_id.text().strip()
        if not issuer or not client_id:
            QMessageBox.warning(self, "إعدادات OIDC", "أدخل Issuer وPublic Client ID.")
            return
        try:
            ReviewApiClient(api_url, "validation-only")
        except ValueError as exc:
            QMessageBox.warning(self, "عنوان API غير صالح", str(exc))
            return
        self.settings.setValue("review/api_url", api_url)
        self.settings.setValue("review/issuer", issuer)
        self.settings.setValue("review/client_id", client_id)
        self._pending_api_url = api_url
        self._run(lambda: OidcPkceLogin(issuer, client_id).login(), self._login_done)

    def _login_done(self, result):
        access_token, expires_in = result
        self.client = ReviewApiClient(self._pending_api_url, access_token)
        self.token_expires_at = time.monotonic() + expires_in
        self.status.setText("تم تسجيل الدخول. رمز الوصول محفوظ في ذاكرة العملية فقط.")
        self._set_busy(False)
        self._refresh_queue()

    def _logout(self):
        if self.client:
            self.client.clear()
        self.client = None
        self.token_expires_at = 0.0
        self.selected_case = None
        self.queue.setRowCount(0)
        self.published.setRowCount(0)
        self.timeline.clear()
        self.status.setText("تم إنهاء الجلسة المحلية وإسقاط مرجع رمز الوصول.")

    def _require_client(self):
        if not self.client:
            raise ReviewAuthError("سجّل الدخول أولاً")
        if time.monotonic() >= self.token_expires_at:
            self._logout()
            raise ReviewAuthError("انتهت مدة رمز الوصول؛ سجّل الدخول مجدداً")
        return self.client

    def _refresh_queue(self):
        client = self._require_client()
        self._run(lambda: client.request("GET", "/api/v1/reviews?limit=250"),
                  self._queue_loaded)

    def _queue_loaded(self, result):
        self.queue_items = result.get("items", [])
        self.queue.setRowCount(len(self.queue_items))
        for row, item in enumerate(self.queue_items):
            values = [
                item.get("review_id"), item.get("field_id"), item.get("status"),
                item.get("assigned_to"), item.get("review_version"),
                item.get("quality_status"), item.get("valid_time"),
            ]
            for col, value in enumerate(values):
                self.queue.setItem(row, col, QTableWidgetItem("" if value is None else str(value)))
        self.status.setText(f"تم تحميل {len(self.queue_items)} حالة مراجعة.")

    def _on_case_selected(self):
        row = self.queue.currentRow()
        if row < 0 or row >= len(self.queue_items):
            self.selected_case = None
            return
        self.selected_case = self.queue_items[row]
        self._set_busy(False)
        case_id = self.selected_case["review_id"]
        client = self.client
        if client:
            self._run(lambda: client.request("GET", f"/api/v1/reviews/{case_id}"),
                      self._case_loaded)

    def _case_loaded(self, case):
        self.selected_case = case
        self.case_title.setText(
            f"الحالة {case['review_id']} — الحقل {case['field_id']} — "
            f"{case['status']} — الإصدار {case['review_version']}"
        )
        lines = []
        for event in case.get("events", []):
            lines.append(
                f"{event.get('created_at','')} | {event.get('actor_id','')} | "
                f"{event.get('event_type','')} | {event.get('note') or ''} | "
                f"{json.dumps(event.get('annotation') or {}, ensure_ascii=False)}"
            )
        self.timeline.setPlainText("\n".join(lines) or "لا توجد أحداث مسجلة.")
        self._set_busy(False)

    def _mutate(self, action, payload, success_message):
        case = self.selected_case
        if not case:
            return
        version = int(case["review_version"])
        body = dict(payload)
        body["expected_version"] = version
        client = self._require_client()
        case_id = case["review_id"]

        def request():
            result = client.request("POST", f"/api/v1/reviews/{case_id}/{action}", body)
            # Return the canonical detail with timeline after successful transition.
            return client.request("GET", f"/api/v1/reviews/{case_id}")

        def done(result):
            self._case_loaded(result)
            self.status.setText(success_message)
            self._refresh_queue()
        self._run(request, done)

    def _assign(self):
        reviewer = self.reviewer_id.text().strip()
        if reviewer:
            self._mutate("assign", {"reviewer_id": reviewer}, "تم إرسال طلب الإسناد.")

    def _open_case(self):
        self._mutate("open", {}, "بدأت المراجعة.")

    def _comment(self):
        note = self.comment_text.text().strip()
        if note:
            self._mutate("comments", {"note": note}, "تم حفظ التعليق.")

    def _decide(self):
        reason = self.reason.text().strip()
        if not reason:
            QMessageBox.warning(self, "سبب القرار مطلوب", "أدخل سبباً واضحاً قبل تسجيل القرار.")
            return
        decision = self.decision.currentData()
        self._mutate("decision", {"decision": decision, "reason": reason},
                     "تم تسجيل القرار. لا يظهر الحقل في النشر إلا إذا اجتاز QC واعتمد.")

    def _reopen(self):
        reason = self.reason.text().strip()
        if not reason:
            QMessageBox.warning(self, "سبب إعادة الفتح مطلوب", "أدخل سبباً واضحاً لإعادة فتح الحالة.")
            return
        self._mutate("reopen", {"reason": reason}, "تم إرسال طلب إعادة فتح الحالة.")

    def _refresh_published(self):
        client = self._require_client()
        self._run(lambda: client.request("GET", "/api/v1/publishable/fields?limit=500"),
                  self._published_loaded)

    def _published_loaded(self, result):
        items = result.get("items", [])
        self.published.setRowCount(len(items))
        for row, item in enumerate(items):
            values = [
                item.get("field_id"), item.get("valid_time"), item.get("forecast_hour"),
                item.get("quality_status"),
                f"run={item.get('run_id')} variable={item.get('variable_id')} grid={item.get('grid_id')}",
            ]
            for col, value in enumerate(values):
                self.published.setItem(row, col, QTableWidgetItem("" if value is None else str(value)))
        self.status.setText(f"قائمة النشر: {len(items)} حقلاً معتمداً ومجتازاً لفحص الجودة.")
