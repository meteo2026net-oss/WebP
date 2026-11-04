#!/usr/bin/env python3
"""Convert compatible GRIB scalar fields into georeferenced PNG map overlays."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import xarray as xr

from .map_render import render_scalar_png


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "field"


def _coordinate(da, names):
    available = {str(k).lower(): str(k) for k in da.coords}
    for name in names:
        if name in available:
            return available[name]
    raise ValueError(f"Missing coordinate {names}; found {list(da.coords)}")


def convert_file(source: Path, output_dir: Path, requested: str | None = None) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ds = xr.open_dataset(source, engine="cfgrib", backend_kwargs={"indexpath": ""})
    products = []
    try:
        candidates = [requested] if requested else list(ds.data_vars)
        for variable in candidates:
            if variable not in ds.data_vars:
                raise KeyError(f"Variable {variable!r} not found. Available: {list(ds.data_vars)}")
            da = ds[variable].squeeze(drop=True)
            if da.ndim != 2:
                continue
            lat_name = _coordinate(da, ("latitude", "lat"))
            lon_name = _coordinate(da, ("longitude", "lon"))
            da = da.transpose(lat_name, lon_name)
            values = np.asarray(da.values, dtype=np.float32)
            lat = np.asarray(da[lat_name].values)
            lon = np.asarray(da[lon_name].values)
            stem = _safe_name(f"{source.stem}_{variable}")
            png_path = output_dir / f"{stem}.png"
            rendered = render_scalar_png(values, lat, lon, png_path)
            metadata = {
                "source_file": source.name,
                "variable": variable,
                "long_name": str(da.attrs.get("long_name", variable)),
                "units": str(da.attrs.get("units", "unknown")),
                "valid_time": str(ds["valid_time"].values) if "valid_time" in ds.coords else None,
                "step": str(ds["step"].values) if "step" in ds.coords else None,
                **rendered,
                "image": png_path.name,
            }
            sidecar = png_path.with_suffix(".json")
            sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            products.append(metadata)
    finally:
        ds.close()
    if not products:
        raise ValueError("No compatible 2-D regular latitude/longitude fields were found. Inspect the GRIB inventory and grid type.")
    return products


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_grib", type=Path)
    parser.add_argument("--variable", help="Exact GRIB variable name; default: all compatible 2-D fields")
    parser.add_argument("--output-dir", type=Path, default=Path("output/map_data"))
    args = parser.parse_args()
    if not args.input_grib.is_file():
        parser.error(f"Input file does not exist: {args.input_grib}")
    products = convert_file(args.input_grib, args.output_dir, args.variable)
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
