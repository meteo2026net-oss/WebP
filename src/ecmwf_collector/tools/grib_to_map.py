#!/usr/bin/env python3
"""Convert compatible GRIB scalar fields into georeferenced PNG map overlays."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import cfgrib

from .map_render import render_scalar_png
from .map_manifest import update_manifest


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "field"


def _coordinate(da, names):
    available = {str(k).lower(): str(k) for k in da.coords}
    for name in names:
        if name in available:
            return available[name]
    raise ValueError(f"Missing coordinate {names}; found {list(da.coords)}")


def _json_scalar(value):
    if hasattr(value, "item"):
        value = value.item()
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


def convert_file(source: Path, output_dir: Path, requested: str | None = None) -> list[dict]:
    """Open all cfgrib hypercube groups; one GRIB may contain multiple level types."""
    output_dir.mkdir(parents=True, exist_ok=True)
    source_id = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:12]
    datasets = cfgrib.open_datasets(str(source), backend_kwargs={"indexpath": ""})
    products = []
    errors = []
    try:
        for group_index, ds in enumerate(datasets):
            candidates = [requested] if requested else list(ds.data_vars)
            for variable in candidates:
                if variable not in ds.data_vars:
                    continue
                try:
                    da = ds[variable].squeeze(drop=True)
                    if da.ndim != 2:
                        continue
                    lat_name = _coordinate(da, ("latitude", "lat"))
                    lon_name = _coordinate(da, ("longitude", "lon"))
                    da = da.transpose(lat_name, lon_name)
                    values = np.asarray(da.values, dtype=np.float32)
                    lat = np.asarray(da[lat_name].values)
                    lon = np.asarray(da[lon_name].values)
                    stem = _safe_name(f"{source.stem}_{source_id}_g{group_index}_{variable}")
                    png_path = output_dir / f"{stem}.png"
                    rendered = render_scalar_png(values, lat, lon, png_path)
                    valid_time = str(ds["valid_time"].values) if "valid_time" in ds.coords else None
                    metadata = {
                        "source_file": source.name,
                        "source_id": source_id,
                        "group_index": group_index,
                        "variable": variable,
                        "long_name": str(da.attrs.get("long_name", variable)),
                        "units": str(da.attrs.get("units", "unknown")),
                        "typeOfLevel": str(da.attrs.get("typeOfLevel", "")),
                        "level": _json_scalar(da.attrs.get("GRIB_level", da.attrs.get("level"))),
                        "valid_time": valid_time,
                        "step": str(ds["step"].values) if "step" in ds.coords else None,
                        **rendered,
                        "image": png_path.name,
                    }
                    data_path = png_path.with_suffix(".npz")
                    np.savez_compressed(data_path, values=values, latitudes=lat, longitudes=lon)
                    metadata["data_file"] = data_path.name
                    sidecar = png_path.with_suffix(".json")
                    sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
                    products.append(metadata)
                except (ValueError, KeyError, TypeError) as exc:
                    errors.append(f"group {group_index}, {variable}: {exc}")
    finally:
        for ds in datasets:
            ds.close()
    if requested and not products:
        raise KeyError(f"Variable {requested!r} was not converted in any GRIB group. Check the inventory.")
    if not products:
        details = "; ".join(errors[:5])
        raise ValueError("No compatible 2-D regular latitude/longitude fields were found. " + details)
    manifest = update_manifest(output_dir, products)
    print(f"Updated map manifest: {manifest}")
    return products


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_grib", type=Path)
    parser.add_argument("--variable", help="Exact variable name; default: all compatible 2-D fields in all GRIB groups")
    parser.add_argument("--output-dir", type=Path, default=Path("output/map_data"))
    args = parser.parse_args()
    if not args.input_grib.is_file():
        parser.error(f"Input file does not exist: {args.input_grib}")
    products = convert_file(args.input_grib, args.output_dir, args.variable)
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
