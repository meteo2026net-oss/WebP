"""Synergie-inspired multi-source meteorological analysis and forecast catalogue.

This module provides an integration workspace, not a copy of Météo-France software.
It indexes local source sidecars and GRIB files without claiming that unavailable
providers are connected or that forecast quality has been verified.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..config import project_root
from ..model_catalog import IMPLEMENTATION_LABELS, MODEL_CATALOG


SOURCE_CATALOG = [
    ("WMO Support", "FMD / FPD / FSD / AND", "موصل FTP موجود"),
    ("ECMWF Open Data", "IFS / AIFS Single / AIFS ENS", "موصل تنزيل وفحص GRIB موجود"),
    ("CPTEC/INPE ETA", "ETA 8 km / 40 km / 1 km", "موصل استعراض وتنزيل وفحص GRIB موجود"),
    ("NOAA / NCEP", "GFS / GEFS / RRFS", "قيد الربط"),
    ("DWD", "ICON / ICON-EU", "قيد الربط"),
    ("UK Met Office", "Global / UKV", "قيد الربط"),
    ("JMA", "GSM / MSM", "قيد الربط"),
    ("Météo-France", "ARPEGE / AROME / PEARP", "قيد الربط"),
    ("Copernicus", "ERA5 / CAMS", "قيد الربط"),
    ("EUMETSAT", "Satellite products", "قيد الربط"),
]

OBSERVATION_LAYERS = [
    ("الرصد السطحي", "محطات SYNOP وMETAR ومحطات الطقس الآلية"),
    ("الرصد العلوي", "بالونات الرصد وTEMP وملفات الرياح والحرارة الرأسية"),
    ("الرادار", "الانعكاسية والهطول والحركة عند توفر تغذية الرادار"),
    ("الأقمار الصناعية", "صور مرئية وتحت الحمراء وبخار الماء والمنتجات المركبة"),
    ("البرق", "رصد ومواقع تفريغ البرق عند توفر مصدر مناسب"),
    ("التحذيرات", "رسائل التحذير والظواهر الشديدة وبيانات CAP"),
]


class ForecastCatalogWidget(QWidget):
    """Index forecast files and source metadata available in the local downloads tree."""

    HEADERS = ["المصدر", "النموذج", "دورة التشغيل UTC", "وقت الصلاحية", "خطوة التنبؤ",
               "المتغيرات", "سلامة الملف", "اسم الملف"]

    def __init__(self, root: Path | None = None):
        super().__init__()
        self.root = Path(root) if root else project_root() / "downloads"
        layout = QVBoxLayout(self)
        intro = QLabel(
            "فهرس موحّد للملفات التي نُزّلت محلياً. تظهر بيانات الدورة والصلاحية فقط "
            "عندما يوفرها المصدر؛ لا تُستنتج القيم المفقودة."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        controls = QHBoxLayout()
        self.filter_source = QComboBox()
        self.filter_source.addItem("كل المصادر")
        self.refresh_button = QPushButton("تحديث الفهرس")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(QLabel("المصدر:"))
        controls.addWidget(self.filter_source)
        controls.addWidget(self.refresh_button)
        controls.addStretch()
        layout.addLayout(controls)
        self.summary = QLabel("لم يُحدّث الفهرس بعد.")
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        self.refresh()

    def _records(self):
        records = []
        if not self.root.exists():
            return records
        sidecar_files = sorted(self.root.rglob("*.source.json"))
        known_files = set()
        for sidecar in sidecar_files:
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            filename = str(meta.get("file") or sidecar.name.removesuffix(".source.json"))
            data = meta.get("request") or {}
            source = meta.get("provider") or meta.get("source") or "مصدر غير محدد"
            model = meta.get("model") or meta.get("domain") or "غير محدد"
            run = meta.get("cycle_utc")
            if run is None and data.get("time") is not None:
                run = f"{data.get('time')}:00"
            if run is None and meta.get("date"):
                run = "غير متاح"
            step = data.get("step")
            params = data.get("param") or []
            if isinstance(params, str):
                params = [params]
            records.append({
                "source": str(source), "model": str(model), "run": str(run or "غير متاح"),
                "valid": str(meta.get("returned_forecast_datetime") or meta.get("valid_time") or "غير متاح"),
                "step": f"{step} ساعة" if step is not None else "غير متاح",
                "params": ", ".join(map(str, params)) or "غير محدد",
                "integrity": str(meta.get("integrity") or "غير مفحوص"),
                "file": filename,
            })
            known_files.add((sidecar.parent / filename).resolve())
        for suffix in ("*.grib", "*.grb", "*.grib2", "*.grb2"):
            for path in self.root.rglob(suffix):
                if path.resolve() in known_files or path.name.endswith(".part"):
                    continue
                records.append({
                    "source": "غير مصنف", "model": "غير محدد", "run": "غير متاح",
                    "valid": "غير متاح", "step": "غير متاح", "params": "افحص الملف",
                    "integrity": "لم يُفحص بواسطة الفهرس", "file": path.name,
                })
        return records

    def refresh(self):
        records = self._records()
        selected = self.filter_source.currentText()
        sources = sorted({r["source"] for r in records})
        self.filter_source.blockSignals(True)
        self.filter_source.clear()
        self.filter_source.addItem("كل المصادر")
        self.filter_source.addItems(sources)
        idx = self.filter_source.findText(selected)
        if idx >= 0:
            self.filter_source.setCurrentIndex(idx)
        self.filter_source.blockSignals(False)
        chosen = self.filter_source.currentText()
        if chosen != "كل المصادر":
            records = [r for r in records if r["source"] == chosen]
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = [record[k] for k in ("source", "model", "run", "valid", "step",
                                           "params", "integrity", "file")]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, col, item)
        self.summary.setText(
            f"الملفات المفهرسة: {len(records)} | مجلد الفهرسة: {self.root} | "
            "سلامة GRIB لا تعني صحة التنبؤ."
        )


class SynergieWorkspace(QWidget):
    """Unified analysis workspace inspired by the SYNERGIE forecaster workflow."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("منظومة SYNERGIE — مساحة العمل التحليلية الموحدة")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)
        description = QLabel(
            "مساحة عمل مستوحاة من مفهوم SYNERGIE لدى Météo-France: جمع النماذج "
            "والرصد والرادار والأقمار الصناعية والتحليل في واجهة واحدة. هذه ليست "
            "نسخة من البرنامج التجاري الأصلي، ولا تعني أن كل التغذيات الخارجية متصلة حالياً."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        source_group = QGroupBox("مصادر النماذج والتنبؤات")
        source_layout = QVBoxLayout(source_group)
        source_table = QTableWidget(len(SOURCE_CATALOG), 3)
        source_table.setHorizontalHeaderLabels(["المصدر", "النماذج / المنتجات", "حالة الربط"])
        source_table.setEditTriggers(QTableWidget.NoEditTriggers)
        source_table.setSelectionBehavior(QTableWidget.SelectRows)
        source_table.setAlternatingRowColors(True)
        source_table.horizontalHeader().setStretchLastSection(True)
        for row, values in enumerate(SOURCE_CATALOG):
            for col, value in enumerate(values):
                source_table.setItem(row, col, QTableWidgetItem(value))
        source_layout.addWidget(source_table)
        layout.addWidget(source_group, 2)
        model_group = QGroupBox("فهرس النماذج العددية والمنتجات — حالة التنفيذ داخل WebP")
        model_layout = QVBoxLayout(model_group)
        model_table = QTableWidget(len(MODEL_CATALOG), 4)
        model_table.setHorizontalHeaderLabels(["المركز / المزود", "النموذج / المنتج", "نوع البيانات", "حالة التنفيذ"])
        model_table.setEditTriggers(QTableWidget.NoEditTriggers)
        model_table.setSelectionBehavior(QTableWidget.SelectRows)
        model_table.setAlternatingRowColors(True)
        model_table.horizontalHeader().setStretchLastSection(True)
        for row, entry in enumerate(MODEL_CATALOG):
            values = (entry.provider, entry.model, entry.product_type,
                      IMPLEMENTATION_LABELS[entry.implementation])
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if entry.notes:
                    item.setToolTip(entry.notes)
                model_table.setItem(row, col, item)
        model_layout.addWidget(model_table)
        layout.addWidget(model_group, 2)
        observation_group = QGroupBox("طبقات الرصد والتحليل التي ستُجمع")
        observation_layout = QVBoxLayout(observation_group)
        observation_table = QTableWidget(len(OBSERVATION_LAYERS), 2)
        observation_table.setHorizontalHeaderLabels(["الطبقة", "البيانات"])
        observation_table.setEditTriggers(QTableWidget.NoEditTriggers)
        observation_table.horizontalHeader().setStretchLastSection(True)
        for row, values in enumerate(OBSERVATION_LAYERS):
            for col, value in enumerate(values):
                observation_table.setItem(row, col, QTableWidgetItem(value))
        observation_layout.addWidget(observation_table)
        layout.addWidget(observation_group, 2)
        footer = QLabel(
            "آلية العمل المستهدفة: استقبال البيانات ← توحيد الوحدات والأوقات والشبكات "
            "← عرض الطبقات ← مقارنة النماذج ← مراجعة خبير الأرصاد ← إنتاج التوقع والتحذير."
        )
        footer.setWordWrap(True)
        layout.addWidget(footer)
