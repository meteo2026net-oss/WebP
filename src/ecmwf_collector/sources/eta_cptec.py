"""CPTEC/INPE ETA model GRIB downloader (Brazil)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin
from urllib.request import Request, urlopen

BASE_URL = "https://dataserver.cptec.inpe.br/dataserver_modelos/eta/"
DOMAINS = ("ams_08km", "ams_40km", "ons_40km", "rjsp_01km")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def list_eta_files(date: str, cycle: str = "00", domain: str = "ams_08km", *, opener=None):
    """Return GRIB filenames published in a CPTEC date/cycle directory."""
    _validate(date, cycle, domain)
    opener = opener or urlopen
    url = _directory_url(date, cycle, domain)
    response = opener(Request(url, headers={"User-Agent": "WebP-weather-data-client/1.0"}), timeout=30)
    with response:
        html = response.read().decode("utf-8", errors="replace")
    parser = _Links()
    parser.feed(html)
    return sorted({
        PurePosixPath(href.split("?", 1)[0]).name
        for href in parser.hrefs
        if PurePosixPath(href.split("?", 1)[0]).name.lower().endswith((".grb", ".grb2", ".grib", ".grib2"))
    })


def retrieve_eta_file(date: str, cycle: str, domain: str, filename: str, target, *, opener=None, catalog_sink=None):
    """Download one explicitly selected GRIB file, validate, hash and publish atomically."""
    _validate(date, cycle, domain)
    if not filename or PurePosixPath(filename).name != filename or not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
        raise ValueError("اسم الملف يجب أن يكون اسماً بسيطاً دون مسارات.")
    opener = opener or urlopen
    directory = _directory_url(date, cycle, domain)
    available = list_eta_files(date, cycle, domain, opener=opener)
    if filename not in available:
        raise FileNotFoundError(f"الملف غير موجود في فهرس CPTEC: {filename}")

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    part.unlink(missing_ok=True)
    url = urljoin(directory, filename)
    try:
        response = opener(Request(url, headers={"User-Agent": "WebP-weather-data-client/1.0"}), timeout=120)
        with response, part.open("wb") as stream:
            while True:
                chunk = response.read(4 * 1024 * 1024)
                if not chunk:
                    break
                stream.write(chunk)
        if not part.is_file() or not part.stat().st_size:
            raise RuntimeError("لم ينتج CPTEC ملفاً غير فارغ.")
        from ecmwf_collector.fileinspect import inspect_file
        check = inspect_file(part)
        if check.verdict != "ok" or not check.kind.startswith("grib"):
            raise RuntimeError(f"فشل فحص GRIB: {check.verdict}: {check.problem}")
        os.replace(part, target)
    except Exception:
        part.unlink(missing_ok=True)
        raise

    digest = hashlib.sha256()
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    report = {
        "source": "CPTEC_INPE_ETA",
        "provider": "CPTEC/INPE, Brazil",
        "domain": domain,
        "date": date,
        "cycle_utc": cycle,
        "filename": filename,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "file": target.name,
        "size_bytes": target.stat().st_size,
        "sha256": digest.hexdigest(),
        "grib_edition": check.kind,
        "message_count": check.messages,
        "integrity": check.verdict,
        "operational_status_note": "Availability is determined from the live CPTEC directory listing; domains may be paused or archived.",
    }
    sidecar_path = target.with_suffix(target.suffix + ".source.json")
    sidecar_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if catalog_sink is not None:
        try:
            report["catalog_registration"] = catalog_sink.register_sidecar(sidecar_path)
        except Exception as exc:
            from ..catalog_errors import CatalogRegistrationError
            raise CatalogRegistrationError(target, sidecar_path, exc) from None
    return report


def _validate(date, cycle, domain):
    if not re.fullmatch(r"\d{8}", date):
        raise ValueError("date يجب أن تكون YYYYMMDD.")
    try:
        datetime.strptime(date, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("تاريخ غير صالح.") from exc
    if cycle not in ("00", "06", "12", "18"):
        raise ValueError("cycle يجب أن تكون 00 أو 06 أو 12 أو 18 UTC.")
    if domain not in DOMAINS:
        raise ValueError(f"domain يجب أن يكون أحد: {', '.join(DOMAINS)}")


def _directory_url(date, cycle, domain):
    return urljoin(BASE_URL, f"{domain}/brutos/{date[:4]}/{date[4:6]}/{date[6:8]}/{cycle}/")


def main():
    parser = argparse.ArgumentParser(description="تنزيل انتقائي من نموذج ETA التابع لـ CPTEC/INPE")
    parser.add_argument("--date", required=True, help="تاريخ الدورة YYYYMMDD")
    parser.add_argument("--cycle", default="00", choices=("00", "06", "12", "18"))
    parser.add_argument("--domain", default="ams_08km", choices=DOMAINS)
    parser.add_argument("--list", action="store_true", help="عرض ملفات GRIB المتاحة دون تنزيل")
    parser.add_argument("--file", help="اسم ملف GRIB كما يظهر في الفهرس")
    parser.add_argument("--output", type=Path, help="مسار حفظ الملف")
    args = parser.parse_args()
    if args.list:
        print("\n".join(list_eta_files(args.date, args.cycle, args.domain)))
        return
    if not args.file or not args.output:
        parser.error("يلزم --file و--output عند التنزيل.")
    print(json.dumps(retrieve_eta_file(args.date, args.cycle, args.domain, args.file, args.output),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
