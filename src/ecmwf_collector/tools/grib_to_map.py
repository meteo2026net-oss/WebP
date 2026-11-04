#!/usr/bin/env python3
"""Convert compatible GRIB scalar fields and forecast slices into map overlays."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
from pathlib import Path

import numpy as np

from .map_render import render_scalar_png
from .map_manifest import update_manifest
from .meteorological_units import convert_values, canonical_unit


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "field"


def _coordinate(da, names):
    available = {str(k).lower(): str(k) for k in da.coords}
    for name in names:
        if name in available:
            return available[name]
    raise ValueError(f"Missing coordinate {names}; found {list(da.coords)}")


def _json_scalar(value):
    """Convert NumPy/xarray scalar metadata to stable JSON-safe values."""
    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else np.datetime_as_string(value, unit="ns")
    if isinstance(value, np.timedelta64):
        return None if np.isnat(value) else str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _json_value(value):
    array = np.asarray(value)
    if array.ndim == 0:
        return _json_scalar(array[()])
    return [_json_scalar(item) for item in array.ravel()]


def _coordinate_value(data_array, name):
    if name in data_array.coords:
        return _json_value(data_array[name].values)
    return None


def convert_file(source: Path, output_dir: Path, requested: str | None = None, display_unit: str | None = None) -> list[dict]:
    """Decode all cfgrib groups and every non-spatial forecast/level slice."""
    try:
        import cfgrib
    except ImportError as exc:
        raise RuntimeError(
            "GRIB conversion requires cfgrib and ecCodes; install the project dependencies first."
        ) from exc

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
                    da = ds[variable]
                    lat_name = _coordinate(da, ("latitude", "lat"))
                    lon_name = _coordinate(da, ("longitude", "lon"))
                    lat_coord, lon_coord = da[lat_name], da[lon_name]
                    if lat_coord.ndim == lon_coord.ndim == 1:
                        lat_dim, lon_dim = lat_coord.dims[0], lon_coord.dims[0]
                        if lat_dim == lon_dim or lat_dim not in da.dims or lon_dim not in da.dims:
                            raise ValueError("Latitude and longitude must map to distinct data dimensions.")
                        spatial_dims = (lat_dim, lon_dim)
                        grid_type = "regular_latitude_longitude"
                    elif lat_coord.ndim == lon_coord.ndim == 2 and lat_coord.dims == lon_coord.dims:
                        spatial_dims = tuple(lat_coord.dims)
                        if len(spatial_dims) != 2 or any(dim not in da.dims for dim in spatial_dims):
                            raise ValueError("2-D geolocation coordinates must map to two data dimensions.")
                        grid_type = str(da.attrs.get("GRIB_gridType", da.attrs.get("gridType", "curvilinear_geolocation")))
                    else:
                        raise ValueError("Latitude/longitude coordinates must both be 1-D or matching 2-D arrays.")
                    extra_dims = [dim for dim in da.dims if dim not in spatial_dims]
                    ranges = [range(da.sizes[dim]) for dim in extra_dims]
                    combinations = itertools.product(*ranges) if ranges else [()]
                    for slice_index, indices in enumerate(combinations):
                        selection = dict(zip(extra_dims, indices))
                        sliced = da.isel(selection).squeeze(drop=True)
                        if sliced.ndim != 2:
                            continue
                        sliced = sliced.transpose(*spatial_dims)
                        values = np.asarray(sliced.values, dtype=np.float32)
                        lat = np.asarray(sliced[lat_name].values)
                        lon = np.asarray(sliced[lon_name].values)
                        slice_parts = []
                        extra_coordinates = {}
                        for dim, index in selection.items():
                            coord_value = _coordinate_value(da, dim)
                            selected_value = coord_value[index] if isinstance(coord_value, list) else index
                            extra_coordinates[dim] = selected_value
                            slice_parts.append(f"{dim}-{selected_value}")
                        suffix = "_" + "_".join(_safe_name(str(part)) for part in slice_parts) if slice_parts else ""
                        stem = _safe_name(f"{source.stem}_{source_id}_g{group_index}_{variable}{suffix}")
                        png_path = output_dir / f"{stem}.png"
                        source_unit = str(sliced.attrs.get("units", "")).strip()
                        if display_unit:
                            if not source_unit:
                                raise ValueError(f"Cannot convert {variable}: source unit metadata is missing.")
                            display_values = np.asarray(convert_values(values, source_unit, display_unit), dtype=np.float32)
                            normalized_display_unit = canonical_unit(display_unit)
                        else:
                            display_values = values
                            normalized_display_unit = source_unit or "unknown"
                        rendered = render_scalar_png(display_values, lat, lon, png_path)
                        valid_time = _coordinate_value(sliced, "valid_time")
                        if valid_time is None:
                            valid_time = _coordinate_value(ds, "valid_time")
                        step = _coordinate_value(sliced, "step")
                        if step is None:
                            step = _coordinate_value(ds, "step")
                        type_of_level = sliced.attrs.get(
                            "GRIB_typeOfLevel", sliced.attrs.get("typeOfLevel", "")
                        )
                        level = sliced.attrs.get("GRIB_level", sliced.attrs.get("level"))
                        if level is None and type_of_level in extra_coordinates:
                            level = extra_coordinates[type_of_level]
                        metadata = {
                            "source_file": source.name,
                            "source_id": source_id,
                            "group_index": group_index,
                            "slice_index": slice_index,
                            "grid_type": grid_type,
                            "variable": variable,
                            "long_name": str(sliced.attrs.get("long_name", variable)),
                            "units": source_unit or "unknown",
                            "source_units": source_unit or "unknown",
                            "display_units": normalized_display_unit,
                            "display_conversion_applied": bool(display_unit),
                            "typeOfLevel": str(type_of_level),
                            "level": _json_scalar(level) if level is not None else None,
                            "extra_coordinates": extra_coordinates,
                            "valid_time": valid_time,
                            "step": step,
                            **rendered,
                            "image": png_path.name,
                        }
                        data_path = png_path.with_suffix(".npz")
                        np.savez_compressed(data_path, values=values, display_values=display_values, latitudes=lat, longitudes=lon)
                        metadata["data_file"] = data_path.name
                        sidecar = png_path.with_suffix(".json")
                        sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
                        products.append(metadata)
                except (ValueError, KeyError, TypeError, IndexError) as exc:
                    errors.append(f"group {group_index}, {variable}: {exc}")
    finally:
        for ds in datasets:
            ds.close()
    if requested and not products:
        if not any(requested in ds.data_vars for ds in datasets):
            raise KeyError(f"Variable {requested!r} was not found in any GRIB group. Check the inventory.")
        details = "; ".join(errors[:5])
        raise ValueError(f"Variable {requested!r} was found but could not be converted. {details}")
    if not products:
        details = "; ".join(errors[:5])
        raise ValueError("No compatible 2-D geographic grid slices were found. " + details)
    manifest = update_manifest(output_dir, products)
    print(f"Updated map manifest: {manifest}")
    return products


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_grib", type=Path)
    parser.add_argument("--variable", help="Exact variable name; default: all compatible variables and forecast slices")
    parser.add_argument("--output-dir", type=Path, default=Path("output/map_data"))
    parser.add_argument("--display-unit", help="Optional display-only unit conversion for the selected --variable; raw source values remain available for point queries.")
    args = parser.parse_args()
    if not args.input_grib.is_file():
        parser.error(f"Input file does not exist: {args.input_grib}")
    if args.display_unit and not args.variable:
        parser.error("--display-unit must be used with --variable so one physical field dimension is converted at a time.")
    products = convert_file(args.input_grib, args.output_dir, args.variable, args.display_unit)
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
