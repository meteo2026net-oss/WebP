"""NOAA/NCEP GEFS 0.5-degree ensemble GRIB2 subset downloader via NOMADS."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import urllib.parse
import urllib.request

from .http_resume import clear_resume_state, download_resumable_with_retry
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_atmos_0p50a.pl"
_ALLOWED_VARIABLES = frozenset({
    "APCP", "CAPE", "CIN", "DPT", "GUST", "HGT", "HPBL", "ICEC",
    "LCDC", "MSLET", "PRMSL", "PWAT", "RH", "SNOD", "SPFH",
    "TCDC", "TMP", "UGRD", "VGRD", "VVEL", "VIS", "WEASD",
})
_LEVEL_RE = re.compile(r"^[a-z0-9_]+$")


class NoaaGefsError(RuntimeError):
    """Raised for invalid GEFS requests or unusable NOMADS responses."""


@dataclass(frozen=True)
class GefsRequest:
    run_date: date
    cycle: int
    forecast_hour: int
    member: str = "c00"
    variables: tuple[str, ...] = ("TMP", "UGRD", "VGRD")
    levels: tuple[str, ...] = ("2_m_above_ground", "10_m_above_ground")

    def validate(self) -> None:
        if self.cycle not in (0, 6, 12, 18):
            raise NoaaGefsError("دورة GEFS يجب أن تكون 00 أو 06 أو 12 أو 18 UTC")
        if not re.fullmatch(r"(?:c00|p(?:0[1-9]|[12][0-9]|30))", self.member):
            raise NoaaGefsError("عضو GEFS يجب أن يكون c00 أو p01 إلى p30")
        if not 3 <= self.forecast_hour <= 384:
            raise NoaaGefsError("ساعة GEFS يجب أن تكون بين 003 و384")
        if self.forecast_hour <= 192 and self.forecast_hour % 3:
            raise NoaaGefsError("حتى الساعة 192 تُتاح ساعات GEFS بمضاعفات 3")
        if self.forecast_hour > 192 and self.forecast_hour % 6:
            raise NoaaGefsError("بعد الساعة 192 تُتاح ساعات GEFS بمضاعفات 6")
        if not self.variables or not self.levels:
            raise NoaaGefsError("يجب تحديد متغير ومستوى واحد على الأقل")
        if len(set(self.variables)) != len(self.variables) or any(
            value not in _ALLOWED_VARIABLES for value in self.variables
        ):
            raise NoaaGefsError("قائمة متغيرات GEFS غير صالحة أو تحتوي على تكرار")
        if len(set(self.levels)) != len(self.levels) or any(
            not _LEVEL_RE.fullmatch(value) for value in self.levels
        ):
            raise NoaaGefsError("قائمة مستويات GEFS غير صالحة أو تحتوي على تكرار")

    @property
    def valid_time(self) -> datetime:
        start = datetime(self.run_date.year, self.run_date.month, self.run_date.day,
                         self.cycle, tzinfo=timezone.utc)
        return start + timedelta(hours=self.forecast_hour)


def build_gefs_url(request: GefsRequest, *, base_url: str = BASE_URL) -> str:
    request.validate()
    day = request.run_date.strftime("%Y%m%d")
    cycle = f"{request.cycle:02d}"
    filename = (
        f"ge{request.member}.t{cycle}z.pgrb2a.0p50.f{request.forecast_hour:03d}"
    )
    params = [("file", filename)]
    params.extend((f"var_{variable}", "on") for variable in request.variables)
    params.extend((f"lev_{level}", "on") for level in request.levels)
    params.extend([
        ("subregion", ""),
        ("dir", f"/gefs.{day}/{cycle}/atmos/pgrb2ap5"),
    ])
    return base_url + "?" + urllib.parse.urlencode(params)


def _verify_grib2(path: Path) -> None:
    if path.stat().st_size < 20:
        raise NoaaGefsError("استجابة GEFS فارغة أو أقصر من الحد الأدنى لملف GRIB2")
    with path.open("rb") as stream:
        head = stream.read(4)
        stream.seek(-4, os.SEEK_END)
        tail = stream.read(4)
    if head != b"GRIB" or tail != b"7777":
        raise NoaaGefsError("استجابة NOMADS ليست ملف GRIB2 مكتمل الإطار")


def download_gefs(request: GefsRequest, output_dir: Path, *, timeout: float = 120,
                  opener=urllib.request.urlopen, catalog_sink=None) -> tuple[Path, Path]:
    """Download one GEFS member, resuming interrupted HTTP transfers safely."""
    url=build_gefs_url(request); output_dir=Path(output_dir); output_dir.mkdir(parents=True,exist_ok=True)
    day=request.run_date.strftime("%Y%m%d"); cycle=f"{request.cycle:02d}"
    stem=f"gefs_{day}_{cycle}z_{request.member}_f{request.forecast_hour:03d}_0p50"
    final_path=output_dir/f"{stem}.grib2"; metadata_path=output_dir/f"{stem}.source.json"
    part_path=output_dir/f"{stem}.grib2.part"
    try:
        digest_hex=download_resumable_with_retry(url,part_path,timeout=timeout,opener=opener)
        _verify_grib2(part_path); os.replace(part_path,final_path); clear_resume_state(part_path)
    except Exception as exc:
        if isinstance(exc,NoaaGefsError): clear_resume_state(part_path); raise
        raise NoaaGefsError(f"تعذر تنزيل GEFS من NOMADS: {type(exc).__name__}: {exc}") from exc
    metadata={
        "source":"NOAA/NCEP NOMADS","model":"GEFS",
        "product":"0.50 degree ensemble atmosphere pgrb2a GRIB2 subset",
        "member":request.member,"run":f"{day}T{cycle}:00:00Z",
        "forecast_hour":request.forecast_hour,
        "valid_time":request.valid_time.isoformat().replace("+00:00","Z"),
        "variables":list(request.variables),"levels":list(request.levels),"resolution":"0p50",
        "downloaded_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
        "file_name":final_path.name,"size_bytes":final_path.stat().st_size,
        "sha256":digest_hex,"source_url":url,
        "integrity":"GRIB2 framing checked; SHA-256 recorded"}
    temp_meta=metadata_path.with_suffix(metadata_path.suffix+".part")
    try:
        temp_meta.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(temp_meta,metadata_path)
    except OSError:
        temp_meta.unlink(missing_ok=True)
        if final_path.exists() and not metadata_path.exists(): final_path.unlink()
        raise
    if catalog_sink is not None:
        catalog_sink.register_sidecar(metadata_path)
    return final_path,metadata_path

def download_gefs_ensemble(request: GefsRequest, output_dir: Path, *,
                           members: tuple[str, ...] | None = None,
                           timeout: float = 120,
                           max_workers: int = 4,
                           opener=urllib.request.urlopen,
                           catalog_sink=None
                           ) -> tuple[list[tuple[str, Path, Path]], list[tuple[str, str]]]:
    """Download independent GEFS members concurrently with bounded connections."""
    selected = members or ("c00", *(f"p{number:02d}" for number in range(1, 31)))
    if len(set(selected)) != len(selected):
        raise NoaaGefsError("قائمة أعضاء GEFS تحتوي على تكرار")
    if isinstance(max_workers, bool) or not isinstance(max_workers, int) or not 1 <= max_workers <= 8:
        raise NoaaGefsError("عدد تنزيلات GEFS المتزامنة يجب أن يكون بين 1 و8")
    for member in selected:
        replace(request, member=member).validate()

    def download_member(member):
        try:
            grib, metadata = download_gefs(
                replace(request, member=member), output_dir,
                timeout=timeout, opener=opener,
            )
            return (member, grib, metadata), None
        except Exception as exc:
            return None, (member, f"{type(exc).__name__}: {exc}")

    completed: list[tuple[str, Path, Path]] = []
    failed: list[tuple[str, str]] = []
    # executor.map preserves requested member order in the manifest while the
    # network transfers themselves run concurrently.
    with ThreadPoolExecutor(max_workers=min(max_workers, len(selected) or 1),
                            thread_name_prefix="gefs-download") as pool:
        for success, error in pool.map(download_member, selected):
            if success is not None:
                completed.append(success)
            if error is not None:
                failed.append(error)
    if catalog_sink is not None:
        # Keep database writes sequential even though member downloads are parallel.
        # A catalogue error does not delete or invalidate an already downloaded GRIB.
        for member, _grib_path, metadata_path in completed:
            try:
                catalog_sink.register_sidecar(metadata_path)
            except Exception as exc:
                failed.append((member, f"catalog registration failed; downloaded file retained ({type(exc).__name__})"))
    return completed, failed



def write_gefs_ensemble_manifest(
    request: GefsRequest,
    output_dir: Path,
    completed: list[tuple[str, Path, Path]],
    failed: list[tuple[str, str]],
    *,
    requested_members: tuple[str, ...] | None = None,
) -> Path:
    """Persist an atomic, auditable summary for one GEFS multi-member batch."""
    request.validate()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    members = requested_members or ("c00", *(f"p{number:02d}" for number in range(1, 31)))
    for member in members:
        replace(request, member=member).validate()
    completed_rows = []
    for member, grib_path, metadata_path in completed:
        completed_rows.append({
            "member": member,
            "file_name": Path(grib_path).name,
            "metadata_file": Path(metadata_path).name,
        })
    failed_rows = [{"member": member, "error": error} for member, error in failed]
    payload = {
        "source": "NOAA/NCEP NOMADS",
        "model": "GEFS",
        "run": f"{request.run_date:%Y%m%d}T{request.cycle:02d}:00:00Z",
        "forecast_hour": request.forecast_hour,
        "valid_time": request.valid_time.isoformat().replace("+00:00", "Z"),
        "resolution": "0p50",
        "variables": list(request.variables),
        "levels": list(request.levels),
        "requested_members": list(members),
        "completed_members": completed_rows,
        "failed_members": failed_rows,
        "summary": {
            "requested": len(members),
            "completed": len(completed_rows),
            "failed": len(failed_rows),
        },
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "note": "Member downloads are independent; this manifest does not contain ensemble statistics.",
    }
    day = request.run_date.strftime("%Y%m%d")
    stem = f"gefs_{day}_{request.cycle:02d}z_f{request.forecast_hour:03d}_ensemble"
    destination = output_dir / f"{stem}.manifest.json"
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, destination)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return destination
