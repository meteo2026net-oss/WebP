"""واجهة إدارة اتصالات قواعد البيانات وتوجيه النماذج."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..connection_profiles import DatabaseProfile, DatabaseProfileStore, test_database_connection
from ..database_routing import DatabaseRoutingError, DatabaseRoutingStore


class _ProfileDialog(QDialog):
    def __init__(self, parent=None, profile: DatabaseProfile | None = None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("إضافة اتصال قاعدة بيانات" if profile is None else "تعديل اتصال قاعدة بيانات")
        self.setLayoutDirection(Qt.RightToLeft)
        form = QFormLayout(self)
        self.name = QLineEdit(profile.name if profile else "")
        self.backend = QComboBox()
        for label, value in (
            ("SQLite", "sqlite"), ("PostgreSQL", "postgresql"),
            ("MySQL", "mysql"), ("MariaDB", "mariadb"),
        ):
            self.backend.addItem(label, value)
        self.database = QLineEdit(profile.database if profile else "")
        self.sqlite_path = QLineEdit(profile.sqlite_path if profile else "")
        self.host = QLineEdit(profile.host if profile else "")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(profile.port if profile and profile.port else 5432)
        self.username = QLineEdit(profile.username if profile else "")
        self.ssl = QComboBox()
        for value in ("prefer", "require", "verify-ca", "verify-full", "disable"):
            self.ssl.addItem(value, value)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("اتركه فارغاً للإبقاء على كلمة المرور الحالية")
        self.enabled = QComboBox()
        self.enabled.addItem("مفعّل", True)
        self.enabled.addItem("معطّل", False)
        if profile:
            self.backend.setCurrentIndex(self.backend.findData(profile.backend))
            self.ssl.setCurrentIndex(self.ssl.findData(profile.ssl_mode))
            self.enabled.setCurrentIndex(self.enabled.findData(profile.enabled))
        self.browse = QPushButton("اختيار ملف…")
        self.browse.clicked.connect(self._browse_sqlite)
        path_row = QHBoxLayout()
        path_row.addWidget(self.sqlite_path, 1)
        path_row.addWidget(self.browse)
        form.addRow("اسم الاتصال", self.name)
        form.addRow("نوع قاعدة البيانات", self.backend)
        form.addRow("ملف SQLite", path_row)
        form.addRow("اسم قاعدة البيانات", self.database)
        form.addRow("المضيف", self.host)
        form.addRow("المنفذ", self.port)
        form.addRow("اسم المستخدم", self.username)
        form.addRow("SSL", self.ssl)
        form.addRow("كلمة المرور", self.password)
        form.addRow("الحالة", self.enabled)
        self.backend.currentIndexChanged.connect(self._update_fields)
        self._update_fields()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse_sqlite(self):
        path, _ = QFileDialog.getOpenFileName(self, "اختر قاعدة SQLite", "", "SQLite (*.db *.sqlite *.sqlite3);;All files (*)")
        if path:
            self.sqlite_path.setText(path)

    def _update_fields(self):
        sqlite = self.backend.currentData() == "sqlite"
        for widget in (self.sqlite_path, self.browse):
            widget.setEnabled(sqlite)
        for widget in (self.database, self.host, self.port, self.username, self.ssl, self.password):
            widget.setEnabled(not sqlite)

    def build_profile(self) -> tuple[DatabaseProfile, str | None]:
        backend = self.backend.currentData()
        profile = DatabaseProfile.create(
            self.name.text().strip(), backend,
            database=self.database.text().strip() if backend != "sqlite" else "",
            host=self.host.text().strip() if backend != "sqlite" else "",
            port=self.port.value() if backend != "sqlite" else None,
            username=self.username.text().strip() if backend != "sqlite" else "",
            ssl_mode=self.ssl.currentData(),
            sqlite_path=self.sqlite_path.text().strip() if backend == "sqlite" else "",
            enabled=self.enabled.currentData(),
        ) if self.profile is None else DatabaseProfile(
            profile_id=self.profile.profile_id,
            name=self.name.text().strip(),
            backend=backend,
            database=self.database.text().strip() if backend != "sqlite" else "",
            host=self.host.text().strip() if backend != "sqlite" else "",
            port=self.port.value() if backend != "sqlite" else None,
            username=self.username.text().strip() if backend != "sqlite" else "",
            ssl_mode=self.ssl.currentData(),
            sqlite_path=self.sqlite_path.text().strip() if backend == "sqlite" else "",
            enabled=self.enabled.currentData(),
            credential_key=self.profile.credential_key,
        )
        profile.validate()
        return profile, self.password.text() or None


class DatabaseManagerWidget(QWidget):
    def __init__(self, secrets, config_root: Path, parent=None):
        super().__init__(parent)
        self.secrets = secrets
        self.profile_store = DatabaseProfileStore(Path(config_root) / "database-profiles.json")
        self.routing_store = None
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("إدارة اتصالات قواعد البيانات — لا تُحفظ كلمات المرور في ملفات JSON"))

        actions = QHBoxLayout()
        self.add_button = QPushButton("إضافة اتصال")
        self.edit_button = QPushButton("تعديل")
        self.test_button = QPushButton("اختبار الاتصال")
        self.toggle_button = QPushButton("تفعيل / تعطيل")
        self.delete_button = QPushButton("حذف الاتصال")
        for button in (self.add_button, self.edit_button, self.test_button, self.toggle_button, self.delete_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.profiles_table = QTableWidget(0, 7)
        self.profiles_table.setHorizontalHeaderLabels(
            ["الاسم", "النوع", "قاعدة البيانات / الملف", "المضيف", "المنفذ", "المستخدم", "الحالة"]
        )
        self.profiles_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.profiles_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.profiles_table, 2)

        layout.addWidget(QLabel("توجيه النماذج والمنتجات إلى قواعد بيانات مستقلة"))
        route_form = QFormLayout()
        self.provider = QLineEdit()
        self.provider.setPlaceholderText("ECMWF / NOAA / DWD")
        self.model = QLineEdit()
        self.model.setPlaceholderText("IFS HRES / GFS / ICON")
        self.product = QLineEdit("GRIB")
        self.route_profile = QComboBox()
        self.default_profile = QComboBox()
        route_form.addRow("المزوّد", self.provider)
        route_form.addRow("النموذج", self.model)
        route_form.addRow("المنتج", self.product)
        route_form.addRow("قاعدة بيانات النموذج", self.route_profile)
        route_form.addRow("قاعدة البيانات الافتراضية", self.default_profile)
        layout.addLayout(route_form)
        route_actions = QHBoxLayout()
        self.save_route_button = QPushButton("حفظ توجيه النموذج")
        self.clear_route_button = QPushButton("مسح التوجيه المحدد")
        route_actions.addWidget(self.save_route_button)
        route_actions.addWidget(self.clear_route_button)
        layout.addLayout(route_actions)
        self.routes_table = QTableWidget(0, 2)
        self.routes_table.setHorizontalHeaderLabels(["مفتاح النموذج / المنتج", "معرّف الاتصال"])
        self.routes_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.routes_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.routes_table, 1)
        self.notice = QLabel("توجيه البيانات يحدد الوجهة فقط؛ لا ينقل البيانات أو يدمجها.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)

        try:
            self.routing_store = DatabaseRoutingStore(Path(config_root) / "database-routing.json", self.profile_store)
        except DatabaseRoutingError as exc:
            self.notice.setText(f"تعذّر تحميل إعدادات التوجيه: {exc}")
        self.add_button.clicked.connect(self._add_profile)
        self.edit_button.clicked.connect(self._edit_profile)
        self.test_button.clicked.connect(self._test_profile)
        self.toggle_button.clicked.connect(self._toggle_profile)
        self.delete_button.clicked.connect(self._delete_profile)
        self.save_route_button.clicked.connect(self._save_route)
        self.clear_route_button.clicked.connect(self._clear_route)
        self.default_profile.currentIndexChanged.connect(self._set_default)
        self.refresh()

    def refresh(self):
        profiles = self.profile_store.list_profiles()
        self.profiles_table.setRowCount(len(profiles))
        for row, profile in enumerate(profiles):
            values = (
                profile.name, profile.backend,
                profile.sqlite_path if profile.backend == "sqlite" else profile.database,
                profile.host or "—", str(profile.port or "—"),
                profile.username or "—", "مفعّل" if profile.enabled else "معطّل",
            )
            for column, value in enumerate(values):
                self.profiles_table.setItem(row, column, QTableWidgetItem(value))
        for combo in (self.route_profile, self.default_profile):
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("— غير محدد —", None)
            for profile in profiles:
                if profile.enabled:
                    combo.addItem(f"{profile.name} ({profile.backend})", profile.profile_id)
            index = combo.findData(previous)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
        self._refresh_routes()

    def _selected_profile(self):
        row = self.profiles_table.currentRow()
        profiles = self.profile_store.list_profiles()
        return profiles[row] if 0 <= row < len(profiles) else None

    def _add_profile(self):
        dialog = _ProfileDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            profile, password = dialog.build_profile()
            if password:
                if not self.profile_store.set_password(profile, self.secrets, password):
                    raise RuntimeError("تعذّر حفظ كلمة المرور في مخزن أسرار النظام.")
            elif profile.backend != "sqlite":
                raise ValueError("أدخل كلمة مرور الاتصال الجديد.")
            self.profile_store.save(profile)
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "تعذّر حفظ الاتصال", str(exc))

    def _edit_profile(self):
        current = self._selected_profile()
        if current is None:
            return
        dialog = _ProfileDialog(self, current)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            updated, password = dialog.build_profile()
            if password and not self.profile_store.set_password(updated, self.secrets, password):
                raise RuntimeError("تعذّر تحديث كلمة المرور في مخزن أسرار النظام.")
            self.profile_store.save(updated)
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "تعذّر تعديل الاتصال", str(exc))

    def _test_profile(self):
        profile = self._selected_profile()
        if profile is None:
            return
        ok, message = test_database_connection(profile, self.secrets)
        QMessageBox.information(self, "اختبار الاتصال", message) if ok else QMessageBox.warning(self, "اختبار الاتصال", message)

    def _toggle_profile(self):
        profile = self._selected_profile()
        if profile is None:
            return
        from dataclasses import replace
        self.profile_store.save(replace(profile, enabled=not profile.enabled))
        self.refresh()

    def _delete_profile(self):
        profile = self._selected_profile()
        if profile is None:
            return
        answer = QMessageBox.question(
            self, "تأكيد حذف الاتصال",
            f"سيُحذف تعريف الاتصال «{profile.name}» من قائمة البرنامج. لن تُحذف قاعدة البيانات أو ملفاتها. متابعة؟",
        )
        if answer != QMessageBox.Yes:
            return
        try:
            if self.routing_store:
                self.routing_store.remove_profile_references(profile.profile_id)
            if not self.profile_store.delete_with_secret(profile.profile_id, self.secrets):
                raise RuntimeError("تعذّر حذف بيانات الاعتماد بالكامل؛ راجع مخزن أسرار النظام.")
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "تعذّر حذف الاتصال", str(exc))

    def _save_route(self):
        if not self.routing_store:
            return
        profile_id = self.route_profile.currentData()
        try:
            if not profile_id:
                raise ValueError("اختر قاعدة بيانات للنموذج.")
            key = self.routing_store.model_key(
                self.provider.text(), self.model.text(), self.product.text()
            )
            self.routing_store.set_route(key, profile_id)
            self._refresh_routes()
        except Exception as exc:
            QMessageBox.warning(self, "تعذّر حفظ التوجيه", str(exc))

    def _set_default(self):
        if not self.routing_store:
            return
        try:
            self.routing_store.set_default(self.default_profile.currentData())
        except Exception as exc:
            QMessageBox.warning(self, "تعذّر تغيير القاعدة الافتراضية", str(exc))

    def _refresh_routes(self):
        if not self.routing_store:
            return
        routes = self.routing_store.snapshot()["routes"]
        self.routes_table.setRowCount(len(routes))
        for row, (key, profile_id) in enumerate(sorted(routes.items())):
            self.routes_table.setItem(row, 0, QTableWidgetItem(key))
            self.routes_table.setItem(row, 1, QTableWidgetItem(profile_id))

    def _clear_route(self):
        if not self.routing_store:
            return
        row = self.routes_table.currentRow()
        item = self.routes_table.item(row, 0) if row >= 0 else None
        if item and self.routing_store.clear_route(item.text()):
            self._refresh_routes()
