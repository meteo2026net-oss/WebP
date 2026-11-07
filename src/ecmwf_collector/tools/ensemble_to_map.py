"""Render GEFS ensemble statistics as map-viewer layers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from .map_manifest import update_manifest
from .map_render import render_scalar_png


def write_gefs_ensemble_map_products(
    statistics: dict, field: dict, output_dir: str | Path, *, source_file: str = "GEFS ensemble"
) -> tuple[list[dict], Path]:
    """Render mean, spread and optional exceedance probability into map layers."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    latitude = np.asarray(field["latitude"])
    longitude = np.asarray(field["longitude"])
    expected_shape = np.asarray(statistics["mean"]).shape
    if expected_shape != np.asarray(statistics["spread"]).shape:
        raise ValueError("GEFS mean and spread arrays must have identical shapes")
    if latitude.ndim == longitude.ndim == 1:
        grid_shape = (latitude.size, longitude.size)
    elif latitude.ndim == longitude.ndim == 2 and latitude.shape == longitude.shape:
        grid_shape = latitude.shape
    else:
        raise ValueError("Unsupported GEFS latitude/longitude coordinate shapes")
    if expected_shape != grid_shape:
        raise ValueError(f"GEFS statistics shape {expected_shape} does not match grid {grid_shape}")

    products = []
    fields = [
        ("mean", "ensemble_mean", "GEFS ensemble mean", str(field["units"])),
        ("spread", "ensemble_spread", "GEFS population standard deviation", str(field["units"])),
    ]
    probability_key = "probability_exceeding_threshold_percent"
    if probability_key in statistics:
        fields.append((
            probability_key, "exceedance_probability",
            "GEFS probability of exceeding threshold", "%",
        ))

    digest = hashlib.sha256()
    digest.update(str(source_file).encode("utf-8"))
    digest.update(str(field["initialization_time"]).encode("utf-8"))
    digest.update(str(field["valid_time"]).encode("utf-8"))
    digest.update(str(field["short_name"]).encode("utf-8"))
    source_id = digest.hexdigest()[:12]

    for key, variable, long_name, units in fields:
        values = np.asarray(statistics[key], dtype=np.float32)
        if values.shape != grid_shape:
            raise ValueError(f"{key} shape {values.shape} does not match grid {grid_shape}")
        stem = f"gefs_{source_id}_{variable}"
        image_path = output_dir / f"{stem}.png"
        rendered = render_scalar_png(values, latitude, longitude, image_path)
        data_path = output_dir / f"{stem}.npz"
        np.savez_compressed(
            data_path, values=values, latitudes=latitude, longitudes=longitude
        )
        metadata = {
            "source_file": source_file,
            "source_id": source_id,
            "group_index": 0,
            "variable": variable,
            "long_name": long_name,
            "units": units,
            "source_units": units,
            "display_units": units,
            "typeOfLevel": str(field["type_of_level"]),
            "level": field["level"],
            "valid_time": field["valid_time"],
            "step": int(field["forecast_hour"]),
            "initialization_time": field["initialization_time"],
            "members": list(field["members"]),
            "image": image_path.name,
            "data_file": data_path.name,
            **rendered,
        }
        sidecar = output_dir / f"{stem}.json"
        sidecar.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        products.append(metadata)

    manifest = update_manifest(output_dir, products)
    return products, manifest
