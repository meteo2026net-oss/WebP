#!/usr/bin/env python3
"""Inventory every GRIB message using the ecCodes Python bindings.

This is intentionally a metadata-only first pass: it does not load full grids
into memory and helps identify the actual fields in an ECMWF delivery.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


# These keys must be readable for an inventory to identify a real GRIB field.
REQUIRED_KEYS = frozenset({"edition", "shortName", "gridType"})

KEYS = (
    "edition", "centre", "dataDate", "dataTime", "validityDate", "validityTime",
    "dataType", "shortName", "name", "units", "paramId", "typeOfLevel",
    "uvRelativeToGrid", "resolutionAndComponentFlags",
    "level", "stepType", "stepRange", "gridType", "Ni", "Nj",
    "latitudeOfFirstGridPointInDegrees", "longitudeOfFirstGridPointInDegrees",
    "latitudeOfLastGridPointInDegrees", "longitudeOfLastGridPointInDegrees",
    "iDirectionIncrementInDegrees", "jDirectionIncrementInDegrees",
    "LaDInDegrees", "LoVInDegrees", "Latin1InDegrees", "Latin2InDegrees",
    "DxInMetres", "DyInMetres", "orientationOfTheGridInDegrees",
    "projectionCentreFlag", "latitudeOfSouthernPoleInDegrees",
    "longitudeOfSouthernPoleInDegrees", "iScansNegatively",
    "jScansPositively", "jPointsAreConsecutive", "alternativeRowScanning",
)


def safe_get(gid: Any, key: str, getter) -> Any:
    """Read an ecCodes key without hiding failures for essential GRIB metadata.

    Optional keys may be absent for a particular grid/message, but silently
    replacing failures for the core identification keys with None makes a
    broken ecCodes installation or undecodable message look like valid data.
    """
    try:
        return getter(gid, key)
    except Exception as exc:
        if key in REQUIRED_KEYS:
            raise RuntimeError(
                f"ecCodes could not read required GRIB key {key!r} "
                f"({type(exc).__name__}): {exc}"
            ) from exc
        return None


def inspect_file(path: Path) -> list[dict[str, Any]]:
    try:
        from eccodes import codes_get, codes_grib_new_from_file, codes_release
    except ImportError as exc:
        raise RuntimeError(
            "GRIB inventory requires the ecCodes Python bindings; install eccodes first."
        ) from exc
    messages: list[dict[str, Any]] = []
    with path.open("rb") as stream:
        index = 0
        while True:
            gid = codes_grib_new_from_file(stream)
            if gid is None:
                break
            index += 1
            try:
                record = {"message": index}
                record.update({key: safe_get(gid, key, codes_get) for key in KEYS})
                messages.append(record)
            finally:
                codes_release(gid)
    if not messages:
        raise ValueError(f"No GRIB messages found in {path}")
    return messages


def main() -> None:
    parser = argparse.ArgumentParser(description="List fields and grid metadata in a GRIB/GRIB2 file.")
    parser.add_argument("input_grib", type=Path)
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    if not args.input_grib.is_file():
        parser.error(f"File does not exist: {args.input_grib}")

    records = inspect_file(args.input_grib)
    report = {
        "source_file": args.input_grib.name,
        "message_count": len(records),
        "messages": records,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Saved inventory: {args.output}")
    print(rendered)


if __name__ == "__main__":
    main()
