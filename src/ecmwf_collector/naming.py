"""تفسير أسماء ملفات WMO Support Dataset وفق وثائق ECMWF.

الصيغة الموثّقة: AADMMDDHHIImmddhhiiE
  AA  : AN تحليل | FM تنبؤ على مستويات النموذج | FP مستويات الضغط | FS السطح
  D   : مصدر البيانات (الوثائق تذكر HRES في موضع وIFS Set-I في مثال؛ لا نعتمد على معناه)
  MMDDHHII (الأول) : وقت الإصدار (الأساس)
  mmddhhii (الثاني): وقت الصلاحية؛ ii=01 يدل على الخطوة صفر للتنبؤ عالي الدقة
  E   : رقم نسخة التجربة
الاسم لا يحمل السنة؛ تُستنتج من تاريخ المجلد. التوقيت يُفترض UTC (عرف ECMWF، غير منصوص عليه في الصفحة).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

KIND_LABELS = {
    "AN": "تحليل",
    "FM": "تنبؤ — مستويات النموذج",
    "FP": "تنبؤ — مستويات الضغط",
    "FS": "تنبؤ — السطح",
}
_RE = re.compile(r"^(AN|FM|FP|FS)([A-Z])(\d{8})(\d{8})([0-9A-Za-z])$")


@dataclass(frozen=True)
class ProductFile:
    kind: str
    source: str
    base: datetime
    valid: datetime
    step_hours: int | None
    step0_marker: bool
    expver: str

    @property
    def label_ar(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


def parse_product_name(name: str, folder_date: date | None = None) -> ProductFile | None:
    m = _RE.match(name)
    if not m:
        return None
    kind, src, b, v, expver = m.groups()
    ref = folder_date or datetime.now(timezone.utc).date()
    bm, bd, bh, bi = int(b[0:2]), int(b[2:4]), int(b[4:6]), int(b[6:8])
    best = None
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            cand = datetime(y, bm, bd, bh, bi, tzinfo=timezone.utc)
        except ValueError:
            continue
        dist = abs((cand.date() - ref).days)
        if best is None or dist < best[0]:
            best = (dist, cand)
    if best is None:
        return None
    base = best[1]
    vm, vd, vh, vi = int(v[0:2]), int(v[2:4]), int(v[4:6]), int(v[6:8])
    marker = vi == 1
    if marker:
        vi = 0
    year = base.year + (1 if (vm, vd, vh, vi) < (base.month, base.day, base.hour, base.minute) else 0)
    try:
        valid = datetime(year, vm, vd, vh, vi, tzinfo=timezone.utc)
    except ValueError:
        return None
    hours = (valid - base).total_seconds() / 3600
    step = int(hours) if hours == int(hours) else None
    return ProductFile(kind, src, base, valid, step, marker, expver)
