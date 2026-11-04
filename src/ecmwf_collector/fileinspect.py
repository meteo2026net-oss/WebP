"""فحص نوع الملف الحقيقي وسلامة بنيته من محتواه، لا من اسمه (الملفات بلا امتداد).

يمرّ على رسائل GRIB/BUFR واحدة بعد أخرى: يتحقق من الطول المعلن ومن الخاتمة 7777
ومن أن مجموع الرسائل يساوي حجم الملف تمامًا. لا يفكّ ضغط البيانات (ذلك للمرحلة 3).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

GRIB, BUFR, END = b"GRIB", b"BUFR", b"7777"


@dataclass(frozen=True)
class FileInspection:
    kind: str          # grib2 | grib1 | bufr | empty | unknown
    verdict: str       # ok | unverified | corrupt
    messages: int = 0
    problem: str = ""

    @property
    def detected_type(self) -> str:
        return {"grib2": "GRIB2", "grib1": "GRIB1", "bufr": "BUFR", "empty": "empty"}.get(self.kind, "unknown")


def inspect_file(path: Path) -> FileInspection:
    path = Path(path)
    size = path.stat().st_size
    if size == 0:
        return FileInspection("empty", "corrupt", 0, "الملف فارغ")
    with open(path, "rb") as f:
        head = f.read(4)
        if head not in (GRIB, BUFR):
            return FileInspection("unknown", "unverified", 0, "صيغة غير معروفة؛ حُفظ الملف كما هو دون تحقق من بنيته")
        pos, count, first_kind = 0, 0, ""
        while pos < size:
            f.seek(pos)
            h = f.read(16)
            if len(h) < 8 or h[:4] not in (GRIB, BUFR):
                return FileInspection(first_kind or "unknown", "corrupt", count,
                                      f"بيانات غير متوقعة عند الإزاحة {pos}")
            ed = h[7]
            if h[:4] == GRIB:
                if ed == 2:
                    if len(h) < 16:
                        return FileInspection("grib2", "corrupt", count, "ترويسة GRIB2 مبتورة")
                    length, kind = int.from_bytes(h[8:16], "big"), "grib2"
                    min_len = 20
                elif ed == 1:
                    length, kind, min_len = int.from_bytes(h[4:7], "big"), "grib1", 12
                    if length & 0x800000:
                        return FileInspection("grib1", "unverified", count, "GRIB1 بترميز طول خاص؛ لم يُتحقق من البنية")
                else:
                    return FileInspection(first_kind or "unknown", "corrupt", count, f"إصدار GRIB غير معروف: {ed}")
            else:
                if ed not in (2, 3, 4):
                    return FileInspection("bufr", "unverified", count, f"إصدار BUFR {ed}؛ لم يُتحقق من البنية")
                length, kind, min_len = int.from_bytes(h[4:7], "big"), "bufr", 12
            first_kind = first_kind or kind
            if length < min_len or pos + length > size:
                return FileInspection(first_kind, "corrupt", count, f"رسالة مبتورة عند الإزاحة {pos}")
            f.seek(pos + length - 4)
            if f.read(4) != END:
                return FileInspection(first_kind, "corrupt", count, f"الرسالة عند {pos} لا تنتهي بـ 7777")
            pos += length
            count += 1
    return FileInspection(first_kind, "ok", count, "")
