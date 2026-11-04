#!/usr/bin/env python3
"""Encode GRIB2 U/V wind components into a lossless RGB WebP texture.

R = encoded U10, G = encoded V10, B = validity mask (0 or 255).
The JSON sidecar stores decoding and grid metadata. The 8-bit encoding is
quantized; lossless WebP preserves encoded bytes, not original float precision.
Keep the source GRIB for scientific calculations.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
import numpy as np
from PIL import Image
from .map_render import render_wind_speed_png
from .map_manifest import update_manifest
from .meteorological_units import canonical_unit

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


def spatial_layout(da: xr.DataArray) -> tuple[str, str, np.ndarray, np.ndarray, str]:
    """Return ordered spatial dimensions and decoder-provided geolocation."""
    lat_name = coord_name(da, ("latitude", "lat"))
    lon_name = coord_name(da, ("longitude", "lon"))
    lat_coord, lon_coord = da[lat_name], da[lon_name]
    if lat_coord.ndim == lon_coord.ndim == 1:
        lat_dim, lon_dim = lat_coord.dims[0], lon_coord.dims[0]
        if lat_dim == lon_dim or lat_dim not in da.dims or lon_dim not in da.dims:
            raise ValueError("1-D latitude and longitude must map to distinct data dimensions.")
        return lat_dim, lon_dim, np.asarray(lat_coord.values), np.asarray(lon_coord.values), "regular_latitude_longitude"
    if (lat_coord.ndim == lon_coord.ndim == 2
            and lat_coord.dims == lon_coord.dims
            and lat_coord.shape == lon_coord.shape):
        dims = tuple(lat_coord.dims)
        if len(dims) != 2 or any(dim not in da.dims for dim in dims):
            raise ValueError("2-D geolocation must map to two data dimensions.")
        return dims[0], dims[1], np.asarray(lat_coord.values), np.asarray(lon_coord.values), "curvilinear_geolocation"
    raise ValueError("Latitude/longitude coordinates must both be 1-D or matching 2-D arrays.")


def wind_speed_and_direction(u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return speed and meteorological direction FROM for earth-relative U/V."""
    u_values, v_values = np.asarray(u, dtype=np.float32), np.asarray(v, dtype=np.float32)
    if u_values.shape != v_values.shape:
        raise ValueError("U and V wind arrays must have identical shapes.")
    speed = np.hypot(u_values, v_values)
    direction = (np.degrees(np.arctan2(-u_values, -v_values)) + 360.0) % 360.0
    direction = np.where(speed > 0, direction, np.nan)
    direction[~(np.isfinite(u_values) & np.isfinite(v_values))] = np.nan
    return speed.astype(np.float32), direction.astype(np.float32)


def rotate_grid_to_earth(u: np.ndarray, v: np.ndarray, angle_degrees: float) -> tuple[np.ndarray, np.ndarray]:
    """Rotate grid-axis components into east/north components.

    Angle is counter-clockwise from true east to positive grid-x. The caller
    must supply a trusted angle; it is never inferred from projection names.
    """
    u_values = np.asarray(u, dtype=np.float64)
    v_values = np.asarray(v, dtype=np.float64)
    if u_values.shape != v_values.shape:
        raise ValueError("U and V wind arrays must have identical shapes.")
    if not np.isfinite(angle_degrees):
        raise ValueError("Grid-to-earth rotation angle must be finite.")
    angle = np.deg2rad(float(angle_degrees))
    cosine, sine = np.cos(angle), np.sin(angle)
    east = u_values * cosine - v_values * sine
    north = u_values * sine + v_values * cosine
    return east.astype(np.float32), north.astype(np.float32)

def optional_bool(value: Any) -> bool | None:
    """Parse decoder boolean metadata without treating the string '0' as true."""
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes"}:
            return True
        if normalized in {"0", "false", "no"}:
            return False
    return None


def compatible_component_units(u_units: Any, v_units: Any) -> str | None:
    """Validate U/V unit agreement without silently converting physical units."""
    u_text = str(u_units).strip() if u_units not in (None, "") else ""
    v_text = str(v_units).strip() if v_units not in (None, "") else ""
    if u_text and v_text:
        try:
            compatible = canonical_unit(u_text) == canonical_unit(v_text)
        except ValueError:
            compatible = " ".join(u_text.lower().split()) == " ".join(v_text.lower().split())
        if not compatible:
            raise ValueError(f"U/V component units differ ({u_text!r} vs {v_text!r}); convert them before encoding.")
    return u_text or v_text or None


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
    try:
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError("Wind GRIB conversion requires xarray and cfgrib; install the GRIB processing dependencies.") from exc
    ds = xr.open_dataset(args.input_grib, engine="cfgrib", backend_kwargs={"indexpath": ""})
    try:
        u_name = find_variable(ds, U_CANDIDATES, args.u_var)
        v_name = find_variable(ds, V_CANDIDATES, args.v_var)
        u_da, v_da = xr.align(ds[u_name].squeeze(drop=True), ds[v_name].squeeze(drop=True), join="exact")
        row_dim, col_dim, lat, lon, grid_type = spatial_layout(u_da)
        if row_dim not in v_da.dims or col_dim not in v_da.dims:
            raise ValueError("U and V components do not share the same spatial dimensions.")
        u_da, v_da = u_da.transpose(row_dim, col_dim), v_da.transpose(row_dim, col_dim)
        u = np.asarray(u_da.values, dtype=np.float32)
        v = np.asarray(v_da.values, dtype=np.float32)
        expected_shape = ((lat.size, lon.size) if lat.ndim == lon.ndim == 1 else lat.shape)
        if u.shape != v.shape or u.shape != expected_shape or lon.shape != lat.shape:
            raise ValueError("Wind arrays and coordinate dimensions do not match.")
        if min(u.shape) < 2:
            raise ValueError("Wind grid must contain at least 2 rows and 2 columns.")
        speed, direction_from = wind_speed_and_direction(u, v)
        lat_name = coord_name(u_da, ("latitude", "lat"))
        lon_name = coord_name(u_da, ("longitude", "lon"))
        units = compatible_component_units(u_da.attrs.get("units"), v_da.attrs.get("units"))
        uv_relative_to_grid = optional_bool(u_da.attrs.get("GRIB_uvRelativeToGrid"))
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
            "units": units,
            "component_frame": ("grid_relative" if uv_relative_to_grid is True else
                                "earth_relative" if uv_relative_to_grid is False else "unknown"),
            "decode": {
                "formula": "value = vmin + (channel / 255) * (vmax - vmin)",
                "vmin": args.vmin,
                "vmax": args.vmax,
                "quantization_step": (args.vmax - args.vmin) / 255.0
            },
            "wind_direction": {
                "convention": "meteorological_from",
                "definition": "degrees clockwise from true north; direction the wind comes from",
                "formula": "(degrees(atan2(-U, -V)) + 360) % 360",
                "calm_wind": "undefined (null/NaN)",
                "valid_for_earth_bearing": (False if uv_relative_to_grid is True else
                                            True if uv_relative_to_grid is False else None),
                "status": ("requires_grid_to_earth_rotation" if uv_relative_to_grid is True else
                           "earth_relative" if uv_relative_to_grid is False else
                           "unknown_reference_frame"),
                "warning": ("U/V are grid-relative; rotate vectors to earth-relative before interpreting direction."
                            if uv_relative_to_grid is True else
                            "Decoder confirms earth-relative U/V." if uv_relative_to_grid is False else
                            "Reference frame is not declared; verify whether U/V are earth-relative before using direction as a true-north bearing.")
            },
            "grid": {
                "grid_type": grid_type,
                "width": int(u.shape[1]),
                "height": int(u.shape[0]),
                "latitude_shape": list(lat.shape),
                "longitude_shape": list(lon.shape),
                "latitude_first": json_value(lat.flat[0]),
                "latitude_last": json_value(lat.flat[-1]),
                "longitude_first": json_value(lon.flat[0]),
                "longitude_last": json_value(lon.flat[-1]),
                "latitude_coordinate": lat_name,
                "longitude_coordinate": lon_name,
                "spatial_dimensions": [row_dim, col_dim]
            },
            "wind_speed_range": {
                "minimum": float(np.nanmin(speed)) if np.any(np.isfinite(speed)) else None,
                "maximum": float(np.nanmax(speed)) if np.any(np.isfinite(speed)) else None
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

        # Also create a transparent, geographically placed display layer.
        map_dir = Path("output/map_data")
        map_dir.mkdir(parents=True, exist_ok=True)
        source_id = hashlib.sha256(str(args.input_grib.resolve()).encode("utf-8")).hexdigest()[:12]
        display_path = map_dir / f"{args.input_grib.stem}_{source_id}_wind_speed.png"
        display_grid = render_wind_speed_png(u, v, lat, lon, display_path)
        speed_path = display_path.with_suffix(".npz")
        np.savez_compressed(speed_path, values=speed, latitudes=lat, longitudes=lon)
        map_record = {
            "source_file": args.input_grib.name,
            "source_id": source_id,
            "variable": "wind_speed",
            "long_name": "Wind speed",
            "units": units or "unknown",
            "valid_time": metadata.get("valid_time") or metadata.get("time"),
            "step": metadata.get("step"),
            "image": display_path.name,
            "data_file": speed_path.name,
            **display_grid,
        }
        update_manifest(map_dir, [map_record])
        metadata["display_layer"] = {
            "image": display_path.name,
            "manifest": str(map_dir / "manifest.json"),
            "bounds": display_grid["bounds"],
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Created scientific texture: {args.output}")
        print(f"Created metadata: {metadata_path}")
        print(f"Created map overlay: {display_path}")
        print(f"Updated map manifest: {map_dir / 'manifest.json'}")
        print(f"Grid: {u.shape[1]} x {u.shape[0]} ({grid_type}); valid cells: {int(valid.sum())}")
        print(f"Encoding range: {args.vmin} .. {args.vmax} {units or 'unknown units'}")
    finally:
        ds.close()

if __name__ == "__main__":
    main()
