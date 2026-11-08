"""واجهة إدارة اتصالات قواعد البيانات وتوجيه النماذج."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..connection_profiles import DatabaseProfile, DatabaseProfileStore, test_database_connection
from ..database_health import inspect_database
from ..database_routing import DatabaseRoutingError, DatabaseRoutingStore
from ..asset_sync import ApprovedCatalogSink, AssetOutboxSynchronizer, CatalogWriteApproval, OutboxSyncApproval


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
        self.ssl_ca = QLineEdit(profile.ssl_ca if profile else "")
        self.ssl_ca_browse = QPushButton("اختيار شهادة CA…")
        self.ssl_ca_browse.clicked.connect(self._browse_ssl_ca)
        ssl_ca_row = QHBoxLayout()
        ssl_ca_row.addWidget(self.ssl_ca, 1)
        ssl_ca_row.addWidget(self.ssl_ca_browse)
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
        form.addRow("شهادة CA (لـ verify-ca/full)", ssl_ca_row)
        form.addRow("كلمة المرور", self.password)
        form.addRow("الحالة", self.enabled)
        self._last_backend = profile.backend if profile else "sqlite"
        self.backend.currentIndexChanged.connect(self._backend_changed)
        self._update_fields()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _backend_changed(self):
        defaults = {"sqlite": 5432, "postgresql": 5432, "mysql": 3306, "mariadb": 3306}
        previous_default = defaults.get(self._last_backend, 5432)
        if self.port.value() == previous_default:
            self.port.setValue(defaults.get(self.backend.currentData(), 5432))
        self._last_backend = self.backend.currentData()
        self._update_fields()

    def _browse_sqlite(self):
        path, _ = QFileDialog.getOpenFileName(self, "اختر قاعدة SQLite", "", "SQLite (*.db *.sqlite *.sqlite3);;All files (*)")
        if path:
            self.sqlite_path.setText(path)

    def _browse_ssl_ca(self):
        path, _ = QFileDialog.getOpenFileName(self, "اختر شهادة CA", "", "Certificates (*.pem *.crt *.cer);;All files (*)")
        if path:
            self.ssl_ca.setText(path)

    def _update_fields(self):
        sqlite = self.backend.currentData() == "sqlite"
        for widget in (self.sqlite_path, self.browse):
            widget.setEnabled(sqlite)
        for widget in (self.database, self.host, self.port, self.username, self.ssl, self.password):
            widget.setEnabled(not sqlite)
        mysql_backend = self.backend.currentData() in {"mysql", "mariadb"}
        self.ssl_ca.setEnabled(mysql_backend)
        self.ssl_ca_browse.setEnabled(mysql_backend)

    def build_profile(self) -> tuple[DatabaseProfile, str | None]:
        backend = self.backend.currentData()
        profile = DatabaseProfile.create(
            self.name.text().strip(), backend,
            database=self.database.text().strip() if backend != "sqlite" else "",
            host=self.host.text().strip() if backend != "sqlite" else "",
            port=self.port.value() if backend != "sqlite" else None,
            username=self.username.text().strip() if backend != "sqlite" else "",
            ssl_mode=self.ssl.currentData(),
            ssl_ca=self.ssl_ca.text().strip() if backend in {"mysql", "mariadb"} else "",
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
            ssl_ca=self.ssl_ca.text().strip() if backend in {"mysql", "mariadb"} else "",
            sqlite_path=self.sqlite_path.text().strip() if backend == "sqlite" else "",
            enabled=self.enabled.currentData(),
            credential_key=self.profile.credential_key,
        )
        profile.validate()
        return profile, self.password.text() or None


class _HealthWorker(QThread):
    completed = Signal(object)

    def __init__(self, profiles, secrets, parent=None):
        super().__init__(parent)
        self.profiles = profiles
        self.secrets = secrets

    def run(self):
        results = [inspect_database(profile, self.secrets) for profile in self.profiles]
        self.completed.emit(results)


class DatabaseManagerWidget(QWidget):
    def __init__(self, secrets, config_root: Path, parent=None):
        super().__init__(parent)
        self.secrets = secrets
        self.profile_store = DatabaseProfileStore(Path(config_root) / "database-profiles.json")
        self.routing_store = None
        self.approved_catalog_sinks = {}
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("إدارة اتصالات قواعد البيانات — لا تُحفظ كلمات المرور في ملفات JSON"))

        actions = QHBoxLayout()
        self.add_button = QPushButton("إضافة اتصال")
        self.edit_button = QPushButton("تعديل")
        self.test_button = QPushButton("اختبار الاتصال")
        self.toggle_button = QPushButton("تفعيل / تعطيل")
        self.delete_button = QPushButton("حذف الاتصال")
        self.health_button = QPushButton("تحديث مؤشرات الصحة")
        for button in (self.add_button, self.edit_button, self.test_button, self.toggle_button, self.delete_button, self.health_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.profiles_table = QTableWidget(0, 7)
        self.profiles_table.setHorizontalHeaderLabels(
            ["الاسم", "النوع", "قاعدة البيانات / الملف", "المضيف", "المنفذ", "المستخدم", "الحالة"]
        )
        self.profiles_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.profiles_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.profiles_table, 2)
        self.health_button.clicked.connect(self._refresh_health)
        layout.addWidget(QLabel("مؤشرات صحة سجل تتبع التنزيلات — قراءة فقط"))
        self.health_table = QTableWidget(0, 10)
        self.health_table.setHorizontalHeaderLabels(
            ["الاتصال", "الحالة", "جدول التتبع", "السجلات", "مكتملة", "فاشلة",
             "الحجم البعيد المسجل", "الحجم المحلي المسجل", "حجم قاعدة البيانات", "آخر تحديث / ملاحظة"]
        )
        self.health_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.health_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.health_table, 1)
        self._health_worker = None

        layout.addWidget(QLabel("توجيه النماذج والمنتجات إلى قواعد بيانات مستقلة"))
        route_form = QFormLayout()
        self.provider = QLineEdit()
        self.provider.setPlaceholderText("ECMWF / NOAA / DWD")
        self.model = QLineEdit()
        self.model.setPlaceholderText("IFS HRES / GFS / ICON")
        self.product = QLineEdit("GRIB")
        self.route_profile = QComboBox()
        self.replica_profile = QComboBox()
        self.default_profile = QComboBox()
        route_form.addRow("المزوّد", self.provider)
        route_form.addRow("النموذج", self.model)
        route_form.addRow("المنتج", self.product)
        route_form.addRow("قاعدة بيانات النموذج", self.route_profile)
        route_form.addRow("قاعدة مزامنة ثانوية", self.replica_profile)
        route_form.addRow("قاعدة البيانات الافتراضية", self.default_profile)
        layout.addLayout(route_form)
        route_actions = QHBoxLayout()
        self.save_route_button = QPushButton("حفظ توجيه النموذج")
        self.clear_route_button = QPushButton("مسح التوجيه المحدد")
        self.approve_catalog_button = QPushButton("اعتماد كتابة الكتالوج…")
        self.sync_catalog_button = QPushButton("مزامنة Outbox…")
        route_actions.addWidget(self.save_route_button)
        route_actions.addWidget(self.clear_route_button)
        route_actions.addWidget(self.approve_catalog_button)
        route_actions.addWidget(self.sync_catalog_button)
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
        self.approve_catalog_button.clicked.connect(self._approve_catalog_writes)
        self.sync_catalog_button.clicked.connect(self._sync_catalog_outbox)
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
        saved_default = (
            self.routing_store.snapshot()["default_profile_id"]
            if self.routing_store else None
        )
        for combo in (self.route_profile, self.replica_profile, self.default_profile):
            previous = combo.currentData()
            if combo is self.default_profile and previous is None:
                previous = saved_default
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

    def _refresh_health(self):
        if self._health_worker is not None and self._health_worker.isRunning():
            return
        profiles = self.profile_store.list_profiles()
        if not profiles:
            QMessageBox.information(self, "مؤشرات الصحة", "أضف اتصالاً واحداً على الأقل أولاً.")
            return
        self.health_button.setEnabled(False)
        self.health_button.setText("جارٍ الفحص…")
        self._health_worker = _HealthWorker(profiles, self.secrets, self)
        self._health_worker.completed.connect(self._show_health)
        self._health_worker.finished.connect(self._health_finished)
        self._health_worker.start()

    def _show_health(self, results):
        self.health_table.setRowCount(len(results))
        for row, result in enumerate(results):
            state = "متصل" if result.connected else "غير متصل"
            table = "متاح" if result.tracking_table_available else "غير موجود"
            count = "—" if result.tracked_files is None else str(result.tracked_files)
            completed = "—" if result.completed_files is None else str(result.completed_files)
            failed = "—" if result.failed_files is None else str(result.failed_files)
            remote_size = "—" if result.remote_bytes is None else f"{result.remote_bytes:,} بايت"
            local_size = "—" if result.local_bytes is None else f"{result.local_bytes:,} بايت"
            database_size = "—" if result.database_bytes is None else f"{result.database_bytes:,} بايت"
            latest = result.latest_update or result.message
            values = (
                result.profile_name, state, table, count, completed, failed,
                remote_size, local_size, database_size, latest,
            )
            for column, value in enumerate(values):
                self.health_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.notice.setText(
            "تنبيه: مؤشرات الجدول تخص بيانات تتبع التنزيلات فقط؛ لا تحصي ملفات CSV الفعلية "
            "ولا أحجام ملفات GRIB/CSV الموجودة على القرص."
        )

    def _health_finished(self):
        self.health_button.setEnabled(True)
        self.health_button.setText("تحديث مؤشرات الصحة")

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
            needs_new_password = updated.backend != "sqlite" and (
                current.backend == "sqlite" or updated.backend != current.backend
            )
            if needs_new_password and not password:
                raise ValueError("أدخل كلمة مرور جديدة عند تغيير نوع قاعدة البيانات.")
            previous_secret = (
                self.secrets.get_password(current.credential_key)
                if current.backend != "sqlite" else None
            )
            secret_updated = False
            removed_old_secret = False
            if password:
                if not self.profile_store.set_password(updated, self.secrets, password):
                    raise RuntimeError("تعذّر تحديث كلمة المرور في مخزن أسرار النظام.")
                secret_updated = True
            if current.backend != "sqlite" and updated.backend == "sqlite":
                if previous_secret is not None:
                    if not self.secrets.delete_password(current.credential_key):
                        raise RuntimeError("تعذّر حذف كلمة المرور القديمة من مخزن أسرار النظام؛ لم يتغير نوع الاتصال.")
                    removed_old_secret = True
            try:
                self.profile_store.save(updated)
            except Exception:
                if removed_old_secret and previous_secret is not None:
                    restored = self.secrets.set_password(current.credential_key, previous_secret)
                    if not restored:
                        raise RuntimeError("فشل حفظ الاتصال وتعذّرت استعادة كلمة المرور القديمة؛ أعد إدخالها قبل الاستخدام.")
                elif secret_updated:
                    if current.backend != "sqlite" and previous_secret is not None:
                        restored = self.secrets.set_password(current.credential_key, previous_secret)
                    else:
                        restored = self.secrets.delete_password(current.credential_key)
                    if not restored:
                        raise RuntimeError("فشل حفظ الاتصال وتعذّر التراجع عن تحديث كلمة المرور؛ أعد مراجعة بيانات الاعتماد.")
                raise
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
        self.approved_catalog_sinks.clear()
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
            self.approved_catalog_sinks.clear()
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "تعذّر حذف الاتصال", str(exc))

    def catalog_sink_for(self, provider: str, model: str, product: str):
        if not self.routing_store:
            return None
        key = self.routing_store.model_key(provider, model, product)
        return self.approved_catalog_sinks.get(key)

    def _approve_catalog_writes(self):
        try:
            key = self.routing_store.model_key(
                self.provider.text(), self.model.text(), self.product.text()
            )
            destination_id = self.route_profile.currentData()
            routed_id = self.routing_store.snapshot()["routes"].get(key)
            if not destination_id or routed_id != destination_id:
                raise ValueError("احفظ توجيه النموذج أولاً وتأكد من تطابق قاعدة الوجهة.")
            replica_id = self.replica_profile.currentData()
            if replica_id == destination_id:
                raise ValueError("قاعدة المزامنة يجب أن تختلف عن قاعدة الوجهة.")
            replica_ids = (replica_id,) if replica_id else ()
            all_ids = (destination_id, *replica_ids)
            names = []
            for profile_id in all_ids:
                profile = self.profile_store.get(profile_id)
                if profile is None or not profile.enabled:
                    raise ValueError("إحدى قواعد البيانات المختارة غير متاحة.")
                names.append(profile.name)
            answer = QMessageBox.question(
                self, "موافقة صريحة على الكتابة",
                "ستُنشأ/تُهيّأ جداول كتالوج الأصول وOutbox وتُسجّل بيانات وصفية بعد التحقق. "
                + "الوجهات: " + "، ".join(names)
                + ". لن تُنسخ ملفات GRIB نفسها ولن تُحذف الملفات المحلية. هل توافق؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            approval = CatalogWriteApproval(
                destination_profile_id=destination_id,
                schema_approved_profile_ids=all_ids,
                replica_profile_ids=replica_ids,
                asset_write_confirmed=True,
            )
            self.approved_catalog_sinks[key] = ApprovedCatalogSink(
                self.profile_store, self.routing_store, self.secrets, approval
            )
            QMessageBox.information(
                self, "تم اعتماد الكتالوج",
                "الاعتماد صالح لهذه الجلسة. مرّر catalog_sink_for(provider, model, product) إلى موصل التنزيل."
            )
        except Exception as exc:
            QMessageBox.warning(self, "تعذّر اعتماد الكتالوج", str(exc))

    def _sync_catalog_outbox(self):
        try:
            key = self.routing_store.model_key(
                self.provider.text(), self.model.text(), self.product.text()
            )
            sink = self.approved_catalog_sinks.get(key)
            if sink is None:
                raise ValueError("اعتمد كتابة الكتالوج أولاً.")
            targets = sink.approval.replica_profile_ids
            if not targets:
                QMessageBox.information(self, "Outbox", "لم يتم اختيار قاعدة مزامنة ثانوية.")
                return
            answer = QMessageBox.question(
                self, "تأكيد المزامنة",
                "سيتم نسخ سجلات كتالوج الأصول المعلقة إلى قاعدة المزامنة المحددة. "
                + "لن تُنقل ملفات GRIB نفسها. هل توافق على هذه الدفعة؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            synchronizer = AssetOutboxSynchronizer(
                sink.approval.destination_profile_id, self.profile_store, self.secrets
            )
            result = synchronizer.sync_pending(
                OutboxSyncApproval(tuple(targets), confirmed=True), limit=100
            )
            QMessageBox.information(
                self, "نتيجة المزامنة",
                f"تم: {result['delivered']} | فشل: {result['failed']} | مؤجل: {result['skipped']}"
            )
        except Exception as exc:
            QMessageBox.warning(self, "تعذّرت المزامنة", str(exc))

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
            self.approved_catalog_sinks.pop(key, None)
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
            self.approved_catalog_sinks.pop(item.text(), None)
            self._refresh_routes()
