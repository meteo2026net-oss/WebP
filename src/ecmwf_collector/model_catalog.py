"""Central, honest inventory of numerical weather models and products.

Statuses describe implementation in WebP, not whether the provider operates the model.
A listed model is not considered downloadable until its provider adapter is implemented.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelEntry:
    provider: str
    model: str
    product_type: str
    implementation: str
    notes: str = ""


MODEL_CATALOG: tuple[ModelEntry, ...] = (
    ModelEntry("ECMWF", "IFS HRES", "تنبؤ حتمي عالمي", "adapter", "موصل ECMWF Open Data؛ يلزم اختبار التنزيل الفعلي لكل دورة وحقل"),
    ModelEntry("ECMWF", "IFS ENS", "تنبؤ احتمالي عالمي", "planned", "يحتاج مسار تنزيل واختبارات مستقلة للأعضاء والإحصاءات"),
    ModelEntry("ECMWF", "AIFS Single", "تنبؤ ذكاء اصطناعي حتمي", "adapter", "خيار نموذج في موصل Open Data؛ لم يُثبت التنزيل الفعلي هنا"),
    ModelEntry("ECMWF", "AIFS ENS", "تنبؤ ذكاء اصطناعي احتمالي", "adapter", "خيار نموذج في موصل Open Data؛ لم يُثبت التنزيل الفعلي هنا"),
    ModelEntry("NOAA", "GFS", "تنبؤ حتمي عالمي", "adapter", "تنزيل GRIB2 مباشر من NOAA/NCEP NOMADS؛ تكامل Windy النقطي منفصل"),
    ModelEntry("NOAA", "GEFS", "تنبؤ احتمالي عالمي", "adapter", "تنزيل GRIB2 للأعضاء c00 وp01–p30، مع manifest للمجموعة؛ لا يحسب إحصاءات ensemble بعد"),
    ModelEntry("NOAA", "RRFS", "تنبؤ إقليمي سريع التحديث", "planned", "يتطلب تحديد منتجات الأرشيف والتوزيع"),
    ModelEntry("DWD", "ICON Global", "تنبؤ حتمي عالمي", "planned"),
    ModelEntry("DWD", "ICON-EU", "تنبؤ حتمي إقليمي", "planned"),
    ModelEntry("DWD", "ICON-D2", "تنبؤ حتمي عالي الدقة", "planned"),
    ModelEntry("UK Met Office", "Global", "تنبؤ حتمي عالمي", "planned"),
    ModelEntry("UK Met Office", "UKV", "تنبؤ حتمي عالي الدقة للمملكة المتحدة", "planned"),
    ModelEntry("JMA", "GSM", "تنبؤ حتمي عالمي", "planned"),
    ModelEntry("JMA", "MSM", "تنبؤ حتمي إقليمي", "planned"),
    ModelEntry("Météo-France", "ARPEGE", "تنبؤ حتمي عالمي", "planned"),
    ModelEntry("Météo-France", "AROME", "تنبؤ حتمي إقليمي عالي الدقة", "planned"),
    ModelEntry("Météo-France", "PEARP", "تنبؤ احتمالي", "planned"),
    ModelEntry("CPTEC/INPE", "ETA", "تنبؤ إقليمي", "adapter", "تنزيل ملفات ETA من نطاقات CPTEC؛ الدقة حسب النطاق المتاح"),
    ModelEntry("Copernicus", "ERA5", "إعادة تحليل مناخي", "planned", "ليس تنبؤاً جوياً تشغيلياً"),
    ModelEntry("Copernicus", "CAMS Global", "تحليل/تنبؤ كيمياء الغلاف الجوي", "planned", "منتج منفصل عن نماذج الطقس التقليدية"),
    ModelEntry("ECMWF", "ecCharts WMS", "خدمة عرض خرائط وطبقات", "wms", "منتج خرائطي وليس نموذجاً عددياً مستقلاً"),
)

IMPLEMENTATION_LABELS = {
    "adapter": "موصل موجود — يحتاج اختبار تشغيل حي",
    "point_adapter": "موصل نقطي فقط — لا ينزّل GRIB",
    "wms": "موصل خرائط WMS — يتطلب اشتراكاً",
    "planned": "لم يُنفّذ بعد",
}


def models_for_provider(provider: str) -> tuple[ModelEntry, ...]:
    """Return catalogue entries for an exact provider name."""
    return tuple(entry for entry in MODEL_CATALOG if entry.provider == provider)


def implementation_counts() -> dict[str, int]:
    """Count catalogue entries by WebP implementation status."""
    counts = {status: 0 for status in IMPLEMENTATION_LABELS}
    for entry in MODEL_CATALOG:
        counts[entry.implementation] += 1
    return counts
