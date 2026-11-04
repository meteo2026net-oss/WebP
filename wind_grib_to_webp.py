#!/usr/bin/env python3
"""Encode GRIB2 U/V wind components into a lossless RGB WebP texture.

R = encoded U10, G = encoded V10, B = validity mask (0 or 255).
The JSON sidecar stores decoding and grid metadata. The 8-bit encoding is
quantized; lossless WebP preserves encoded bytes, not original float precision.
Keep the source GRIB for scientific calculations.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any
import numpy as np
import xarray as xr
from PIL import Image

U_CANDIDATES = ("u10", "10u", "u_10m", "u")
V_CANDIDATES = ("v10", "10v", "v_10m", "v")

def find_variable(ds: xr.Dataset, candidates: tuple[str, ...], requested: str | None) -> str:
    if requested:
        if requested not in ds.data_vars:
            raise KeyError(f"Variable {requested!r} not found. Available: {list(ds.data_vars)}")
        return requested
    names = {name.lower(): name for name in ds.data_vars}
    for candidate in candidates:
        if candidate in names:
            return names[candidate]
    raise KeyError(f"Could not identify {candidates}; available: {list(ds.data_vars)}. Use --u-var/--v-var.")

def coord_name(da: xr.DataArray, candidates: tuple[str, ...]) -> str:
    names = {name.lower(): name for name in da.coords}
    for candidate in candidates:
        if candidate in names:
            return names[candidate]
    raise KeyError(f"Missing coordinate {candidates}; found {list(da.coords)}")

def encode_component(values: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    scaled = (np.clip(values, vmin, vmax) - vmin) * (255.0 / (vmax - vmin))
    return np.rint(scaled).astype(np.uint8)

def json_value(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)

def main() -> None:
    parser = argparse.ArgumentParser(description="Convert GRIB U/V wind fields to RGB lossless WebP.")
    parser.add_argument("input_grib", type=Path, help="Input GRIB/GRIB2 file")
    parser.add_argument("--output", type=Path, default=Path("output/wind.webp"))
    parser.add_argument("--u-var", help="U component variable name")
    parser.add_argument("--v-var", help="V component variable name")
    parser.add_argument("--vmin", type=float, default=-100.0)
    parser.add_argument("--vmax", type=float, default=100.0)
    args = parser.parse_args()
    if not args.input_grib.is_file():
        raise FileNotFoundError(args.input_grib)
    if not args.vmin < args.vmax:
        raise ValueError("--vmin must be smaller than --vmax")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ds = xr.open_dataset(args.input_grib, engine="cfgrib", backend_kwargs={"indexpath": ""})
    try:
        u_name = find_variable(ds, U_CANDIDATES, args.u_var)
        v_name = find_variable(ds, V_CANDIDATES, args.v_var)
        u_da, v_da = xr.align(ds[u_name].squeeze(drop=True), ds[v_name].squeeze(drop=True), join="exact")
        lat_name = coord_name(u_da, ("latitude", "lat"))
        lon_name = coord_name(u_da, ("longitude", "lon"))
        lat, lon = np.asarray(u_da[lat_name].values), np.asarray(u_da[lon_name].values)
        if lat.ndim != 1 or lon.ndim != 1:
            raise ValueError("Only 1-D latitude/longitude grids are supported; reproject other grids first.")
        u_da, v_da = u_da.transpose(lat_name, lon_name), v_da.transpose(lat_name, lon_name)
        u = np.asarray(u_da.values, dtype=np.float32)
        v = np.asarray(v_da.values, dtype=np.float32)
        if u.shape != v.shape or u.shape != (lat.size, lon.size):
            raise ValueError("Wind arrays and coordinate dimensions do not match.")
        valid = np.isfinite(u) & np.isfinite(v)
        rgb = np.zeros((u.shape[0], u.shape[1], 3), dtype=np.uint8)
        rgb[..., 0] = encode_component(np.where(valid, u, args.vmin), args.vmin, args.vmax)
        rgb[..., 1] = encode_component(np.where(valid, v, args.vmin), args.vmin, args.vmax)
        rgb[..., 2] = np.where(valid, 255, 0).astype(np.uint8)
        Image.fromarray(rgb, mode="RGB").save(args.output, format="WEBP", lossless=True, quality=100, method=6)
        metadata = {
            "format": "RGB lossless WebP",
            "encoding_version": 1,
            "source_file": args.input_grib.name,
            "u_variable": u_name,
            "v_variable": v_name,
            "channels": {
                "R": "U wind component",
                "G": "V wind component",
                "B": "validity mask: 0=missing, 255=valid"
            },
            "units": json_value(u_da.attrs.get("units", v_da.attrs.get("units", "m s-1"))),
            "decode": {
                "formula": "value = vmin + (channel / 255) * (vmax - vmin)",
                "vmin": args.vmin,
                "vmax": args.vmax,
                "quantization_step": (args.vmax - args.vmin) / 255.0
            },
            "grid": {
                "width": int(lon.size),
                "height": int(lat.size),
                "latitude_first": float(lat[0]),
                "latitude_last": float(lat[-1]),
                "longitude_first": float(lon[0]),
                "longitude_last": float(lon[-1]),
                "latitude_ascending": bool(lat[-1] > lat[0]),
                "longitude_ascending": bool(lon[-1] > lon[0]),
                "latitude_coordinate": lat_name,
                "longitude_coordinate": lon_name
            },
            "valid_pixel_count": int(valid.sum()),
            "missing_pixel_count": int((~valid).sum()),
            "notes": [
                "Keep the original GRIB for scientific calculations.",
                "8-bit encoding is quantized; lossless WebP preserves encoded bytes only.",
                "Check projection and longitude convention before map placement."
            ]
        }
        for name in ("valid_time", "time", "forecast_reference_time", "step"):
            if name in ds.coords:
                value = np.asarray(ds[name].values)
                metadata[name] = json_value(value) if value.ndim == 0 else [json_value(x) for x in value.ravel()]
        metadata_path = args.output.with_suffix(".json")
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Created texture: {args.output}")
        print(f"Created metadata: {metadata_path}")
        print(f"Grid: {lon.size} x {lat.size}; valid cells: {int(valid.sum())}")
        print(f"Encoding range: {args.vmin} .. {args.vmax} m/s")
    finally:
        ds.close()

if __name__ == "__main__":
    main()
