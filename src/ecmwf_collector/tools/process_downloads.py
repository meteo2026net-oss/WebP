#!/usr/bin/env python3
"""Scan downloaded GRIB files and create map overlays for compatible fields."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

from .grib_to_map import convert_file
from .inspect_grib import inspect_file


def _safe_stem(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", path.stem).strip("._") or "grib_file"


def process_tree(download_root: Path, output_root: Path) -> dict:
    download_root = Path(download_root)
    output_root = Path(output_root)
    if not download_root.exists():
        raise FileNotFoundError(f"Download directory not found: {download_root}")
    candidates = []
    ignored = {".part", ".invalid", ".json", ".png", ".webp", ".npz", ".csv", ".db"}
    for path in download_root.rglob("*"):
        if path.is_file() and path.suffix.lower() not in ignored and not path.name.startswith("."):
            candidates.append(path)
    results = {"scanned": len(candidates), "converted": [], "failed": []}
    for source in sorted(candidates):
        try:
            inspect_file(source)  # ecCodes confirms the file is a readable GRIB stream
            products = convert_file(source, output_root, None)
            results["converted"].append({"source": str(source), "layers": len(products)})
        except Exception as exc:
            results["failed"].append({"source": str(source), "error": f"{type(exc).__name__}: {exc}"})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--downloads", type=Path, default=Path("downloads"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/map_data"))
    args = parser.parse_args()
    report = process_tree(args.downloads, args.output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Converted {len(report['converted'])} files; failures/skips: {len(report['failed'])}.")


if __name__ == "__main__":
    main()
