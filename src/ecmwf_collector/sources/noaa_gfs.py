"""NOAA/NCEP GFS 0.25-degree GRIB2 subset downloader via NOMADS.

The downloader requests one forecast lead at a time and writes an auditable
JSON sidecar beside each verified GRIB2 file. It never stores credentials.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
DEFAULT_VARIABLES = {
    "TMP": "2_m_above_ground",
    "DPT": "2_m_above_ground",
    "RH": "2_m_above_ground",
    "UGRD": "10_m_above_ground",
    "VGRD": "10_m_above_ground",
    "GUST": "surface",
    "PRMSL": "mean_sea_level",
    "APCP": "surface",
    "TCDC": "entire_atmosphere",
}
_ALLOWED_VARIABLES = frozenset({
    "4LFTX", "ABSV", "ACPCP", "APCP", "CAPE", "CIN", "DPT", "GUST",
    "HGT", "HPBL", "ICEC", "LCDC", "MSLET", "PRATE", "PRMSL", "PWAT",
    "RH", "SNOD", "SOILW", "SPFH", "TCDC", "TMP", "UGRD", "VGRD",
    "VVEL", "VIS", "WEASD",
})
_LEVEL_RE = re.compile(r"^[a-z0-9_]+$")


class NoaaGfsError(RuntimeError):
    """Raised for invalid requests, unavailable data, or invalid GRIB2 payloads."""


@dataclass(frozen=True)
class GfsRequest:
    run_date: date
    cycle: int
    forecast_hour: int
    variables: tuple[str, ...] = ("TMP", "UGRD", "VGRD")
    levels: tuple[str, ...] = ("2_m_above_ground", "10_m_above_ground")
    resolution: str = "0p25"

    def validate(self) -> None:
        if self.cycle not in (0, 6, 12, 18):
            raise NoaaGfsError("دورة GFS يجب أن تكون 00 أو 06 أو 12 أو 18 UTC")
        if not 0 <= self.forecast_hour <= 384:
            raise NoaaGfsError("ساعة التنبؤ يجب أن تكون بين 000 و384")
        if self.forecast_hour > 120 and self.forecast_hour % 3:
            raise NoaaGfsError("بعد الساعة 120 يجب اختيار ساعة من مضاعفات 3")
        if self.resolution != "0p25":
            raise NoaaGfsError("الإصدار الحالي يدعم شبكة GFS بدقة 0.25 درجة فقط")
        if not self.variables or not self.levels:
            raise NoaaGfsError("يجب تحديد متغير واحد ومستوى واحد على الأقل")
        if len(set(self.variables)) != len(self.variables):
            raise NoaaGfsError("قائمة المتغيرات تحتوي على تكرار")
        if len(set(self.levels)) != len(self.levels):
            raise NoaaGfsError("قائمة المستويات تحتوي على تكرار")
        if any(v not in _ALLOWED_VARIABLES for v in self.variables):
            raise NoaaGfsError("تتضمن قائمة المتغيرات رمزاً غير مدعوم")
        if any(not _LEVEL_RE.fullmatch(level) for level in self.levels):
            raise NoaaGfsError("رمز مستوى غير صالح")

    @property
    def valid_time(self) -> datetime:
        start = datetime(self.run_date.year, self.run_date.month, self.run_date.day,
                         self.cycle, tzinfo=timezone.utc)
        return start + timedelta(hours=self.forecast_hour)


def build_gfs_url(request: GfsRequest, *, base_url: str = BASE_URL) -> str:
    request.validate()
    day = request.run_date.strftime("%Y%m%d")
    cycle = f"{request.cycle:02d}"
    filename = f"gfs.t{cycle}z.pgrb2.{request.resolution}.f{request.forecast_hour:03d}"
    params = [("file", filename)]
    params.extend((f"var_{variable}", "on") for variable in request.variables)
    params.extend((f"lev_{level}", "on") for level in request.levels)
    params.extend([
        ("subregion", ""),
        ("dir", f"/gfs.{day}/{cycle}/atmos"),
    ])
    return base_url + "?" + urllib.parse.urlencode(params)


def _verify_grib2(path: Path) -> None:
    size = path.stat().st_size
    if size < 20:
        raise NoaaGfsError("الاستجابة فارغة أو أقصر من الحد الأدنى لملف GRIB2")
    with path.open("rb") as stream:
        head = stream.read(4)
        stream.seek(-4, os.SEEK_END)
        tail = stream.read(4)
    if head != b"GRIB" or tail != b"7777":
        raise NoaaGfsError("الاستجابة ليست ملف GRIB2 مكتملًا؛ لن تُنشر كملف نهائي")


def download_gfs(request: GfsRequest, output_dir: Path, *, timeout: float = 90,
                 opener=urllib.request.urlopen) -> tuple[Path, Path]:
    """Download one NOMADS-filtered GFS field file and its metadata sidecar."""
    url = build_gfs_url(request)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    day = request.run_date.strftime("%Y%m%d")
    cycle = f"{request.cycle:02d}"
    stem = f"gfs_{day}_{cycle}z_f{request.forecast_hour:03d}_0p25"
    final_path = output_dir / f"{stem}.grib2"
    metadata_path = output_dir / f"{stem}.source.json"
    part_path = output_dir / f"{stem}.grib2.part"

    digest = hashlib.sha256()
    try:
        response = opener(url, timeout=timeout)
        with response, part_path.open("wb") as target:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
                digest.update(chunk)
        _verify_grib2(part_path)
        os.replace(part_path, final_path)
    except Exception as exc:
        if isinstance(exc, NoaaGfsError):
            raise
        raise NoaaGfsError(f"تعذر تنزيل GFS من NOMADS: {type(exc).__name__}: {exc}") from exc

    metadata = {
        "source": "NOAA/NCEP NOMADS",
        "model": "GFS",
        "product": "0.25 degree GRIB2 filtered subset",
        "run": f"{day}T{cycle}:00:00Z",
        "forecast_hour": request.forecast_hour,
        "valid_time": request.valid_time.isoformat().replace("+00:00", "Z"),
        "variables": list(request.variables),
        "levels": list(request.levels),
        "resolution": request.resolution,
        "downloaded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "file_name": final_path.name,
        "size_bytes": final_path.stat().st_size,
        "sha256": digest.hexdigest(),
        "source_url": url,
        "integrity": "GRIB2 framing checked; SHA-256 recorded",
    }
    temp_meta = metadata_path.with_suffix(metadata_path.suffix + ".part")
    temp_meta.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_meta, metadata_path)
    return final_path, metadata_path
