#!/usr/bin/env python3
"""Build a streaming, deduplicated inventory for ECMWF/WMO GRIB deliveries.

The scanner hashes files in chunks (never reads a whole 17+ GB delivery into
RAM), validates the outer GRIB framing, and optionally inventories each GRIB
message with ecCodes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from ecmwf_collector.fileinspect import inspect_file as inspect_binary
from ecmwf_collector.tools.inspect_grib import inspect_file as inspect_messages

PRODUCT_TYPES = {"AND", "FMD", "FPD", "FSD"}
SUMMARY_KEYS = (
    "edition", "shortName", "name", "units", "paramId",
    "typeOfLevel", "level", "stepType", "stepRange",
    "dataDate", "dataTime", "validityDate", "validityTime",
)

def product_type(filename: str) -> str:
    """Classify the four WMO delivery filename prefixes without guessing others."""
    prefix = Path(filename).name[:3].upper()
    return prefix if prefix in PRODUCT_TYPES else "OTHER"

def is_candidate(path: Path) -> bool:
    """Keep WMO extensionless products and conventional GRIB files; skip partials."""
    if path.name.startswith(".") or path.suffix.lower() in {".part", ".invalid", ".tmp"}:
        return False
    return product_type(path.name) in PRODUCT_TYPES or path.suffix.lower() in {
        ".grib", ".grib1", ".grib2", ".grb", ".grb1", ".grb2"
    }

def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()

def _message_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    fields: dict[str, set[str]] = defaultdict(set)
    valid_times: set[str] = set()
    for record in records:
        for key in SUMMARY_KEYS:
            value = record.get(key)
            if value is not None:
                fields[key].add(str(value))
        date, time = record.get("validityDate"), record.get("validityTime")
        if date is not None and time is not None:
            valid_times.add(f"{date}T{int(time):04d}Z")
    return {
        "fields": {key: sorted(values) for key, values in sorted(fields.items())},
        "valid_times_utc": sorted(valid_times),
    }

def build_catalog(root: Path, decode_metadata: bool = True) -> dict[str, Any]:
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and is_candidate(path)
    )
    seen_hashes: dict[str, str] = {}
    totals: Counter[str] = Counter()
    product_stats: dict[str, Counter[str]] = defaultdict(Counter)
    entries: list[dict[str, Any]] = []
    for index, path in enumerate(files, 1):
        relative = path.relative_to(root).as_posix()
        kind = product_type(path.name)
        size = path.stat().st_size
        digest = sha256_file(path)
        binary = inspect_binary(path)
        duplicate_of = seen_hashes.get(digest)
        if duplicate_of is None:
            seen_hashes[digest] = relative
        entry: dict[str, Any] = {
            "path": relative, "product_type": kind, "size_bytes": size,
            "sha256": digest, "detected_format": binary.detected_type,
            "integrity": binary.verdict, "message_count": binary.messages,
            "problem": binary.problem or None, "duplicate_of": duplicate_of,
        }
        if decode_metadata and binary.kind in {"grib1", "grib2"} and binary.verdict == "ok":
            try:
                records = inspect_messages(path)
                entry["message_count"] = len(records)
                entry["metadata"] = _message_summary(records)
            except Exception as exc:
                entry["metadata_error"] = f"{type(exc).__name__}: {exc}"
        entries.append(entry)
        totals["files"] += 1
        totals["bytes"] += size
        product_stats[kind]["files"] += 1
        product_stats[kind]["bytes"] += size
        product_stats[kind]["messages"] += int(entry["message_count"] or 0)
        product_stats[kind]["duplicates"] += int(duplicate_of is not None)
        print(f"[{index}/{len(files)}] {relative} | {size:,} bytes | {binary.verdict}")
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root), "hash_algorithm": "SHA-256",
        "hash_chunk_size_bytes": 4 * 1024 * 1024,
        "totals": {
            "files": totals["files"], "bytes": totals["bytes"],
            "gib": round(totals["bytes"] / (1024 ** 3), 3),
            "messages": sum(stats["messages"] for stats in product_stats.values()),
            "unique_files": len(seen_hashes),
            "duplicates": totals["files"] - len(seen_hashes),
        },
        "by_product_type": {
            name: {
                "files": stats["files"], "bytes": stats["bytes"],
                "gib": round(stats["bytes"] / (1024 ** 3), 3),
                "messages": stats["messages"], "duplicates": stats["duplicates"],
            }
            for name, stats in sorted(product_stats.items())
        },
        "files": entries,
    }

def main() -> None:
    parser = argparse.ArgumentParser(
        description="فهرسة ملفات AND/FMD/FPD/FSD مع بصمة SHA-256 وفحص GRIB"
    )
    parser.add_argument("downloads", type=Path, help="مجلد الملفات المنزلة")
    parser.add_argument("--output", type=Path, default=Path("output/grib_catalog.json"))
    parser.add_argument(
        "--no-metadata", action="store_true",
        help="فحص البنية والبصمات فقط دون قراءة حقول GRIB عبر ecCodes",
    )
    args = parser.parse_args()
    report = build_catalog(args.downloads, decode_metadata=not args.no_metadata)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(
        f"\nتم إنشاء الفهرس: {args.output}\n"
        f"الملفات: {report['totals']['files']} | "
        f"الحجم: {report['totals']['gib']} GiB | "
        f"المكرر: {report['totals']['duplicates']}"
    )

if __name__ == "__main__":
    main()
