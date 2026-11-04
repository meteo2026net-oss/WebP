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
        return None if np.isnat(value) else np.datetime_as_string(value, unit="auto")
    if isinstance(value, np.timedelta64):
        return None if np.isnat(value) else np.timedelta_as_string(value)
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
        return _json_scalar(array.item())
    return [_json_scalar(item) for item in array.ravel()]


def _coordinate_value(data_array, name):
    if name in data_array.coords:
        return _json_value(data_array[name].values)
    return None


def convert_file(source: Path, output_dir: Path, requested: str | None = None) -> list[dict]:
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
                    if lat_coord.ndim != 1 or lon_coord.ndim != 1:
                        raise ValueError("Only 1-D latitude/longitude coordinate arrays are supported.")
                    lat_dim, lon_dim = lat_coord.dims[0], lon_coord.dims[0]
                    if lat_dim == lon_dim or lat_dim not in da.dims or lon_dim not in da.dims:
                        raise ValueError("Latitude and longitude must map to distinct data dimensions.")
                    extra_dims = [dim for dim in da.dims if dim not in (lat_dim, lon_dim)]
                    ranges = [range(da.sizes[dim]) for dim in extra_dims]
                    combinations = itertools.product(*ranges) if ranges else [()]
                    for slice_index, indices in enumerate(combinations):
                        selection = dict(zip(extra_dims, indices))
                        sliced = da.isel(selection).squeeze(drop=True)
                        if sliced.ndim != 2:
                            continue
                        sliced = sliced.transpose(lat_dim, lon_dim)
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
                        rendered = render_scalar_png(values, lat, lon, png_path)
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
                            "variable": variable,
                            "long_name": str(sliced.attrs.get("long_name", variable)),
                            "units": str(sliced.attrs.get("units", "unknown")),
                            "typeOfLevel": str(type_of_level),
                            "level": _json_scalar(level) if level is not None else None,
                            "extra_coordinates": extra_coordinates,
                            "valid_time": valid_time,
                            "step": step,
                            **rendered,
                            "image": png_path.name,
                        }
                        data_path = png_path.with_suffix(".npz")
                        np.savez_compressed(data_path, values=values, latitudes=lat, longitudes=lon)
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
        raise KeyError(f"Variable {requested!r} was not converted in any GRIB group. Check the inventory.")
    if not products:
        details = "; ".join(errors[:5])
        raise ValueError("No compatible 2-D regular latitude/longitude slices were found. " + details)
    manifest = update_manifest(output_dir, products)
    print(f"Updated map manifest: {manifest}")
    return products


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_grib", type=Path)
    parser.add_argument("--variable", help="Exact variable name; default: all compatible variables and forecast slices")
    parser.add_argument("--output-dir", type=Path, default=Path("output/map_data"))
    args = parser.parse_args()
    if not args.input_grib.is_file():
        parser.error(f"Input file does not exist: {args.input_grib}")
    products = convert_file(args.input_grib, args.output_dir, args.variable)
    print(json.dumps(products, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
