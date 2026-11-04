"""Geographic normalization and PNG rendering helpers for regular lat/lon grids."""
from __future__ import annotations

import numpy as np
from PIL import Image

# A readable sequential palette for scalar weather fields.
SCALAR_STOPS = np.array([
    [35, 45, 110], [45, 95, 170], [45, 155, 190], [75, 185, 120],
    [205, 205, 65], [235, 145, 45], [195, 65, 55], [245, 235, 225],
], dtype=np.float32)


def normalize_regular_grid(values: np.ndarray, latitudes: np.ndarray, longitudes: np.ndarray):
    """Return data ordered north-to-south and west-to-east on a -180..180 grid."""
    data = np.asarray(values, dtype=np.float32)
    lat = np.asarray(latitudes, dtype=np.float64)
    lon = np.asarray(longitudes, dtype=np.float64)
    if lat.ndim != 1 or lon.ndim != 1:
        raise ValueError("Only regular 1-D latitude/longitude coordinates are supported.")
    if data.shape != (lat.size, lon.size):
        raise ValueError(f"Data shape {data.shape} does not match coordinates {(lat.size, lon.size)}")
    if lat.size < 2 or lon.size < 2:
        raise ValueError("At least two latitude and longitude points are required.")
    if not np.all(np.isfinite(lat)) or not np.all(np.isfinite(lon)):
        raise ValueError("Coordinates contain non-finite values.")
    lat_steps = np.abs(np.diff(lat))
    if not np.allclose(lat_steps, np.median(lat_steps), rtol=1e-3, atol=1e-6):
        raise ValueError("Latitude coordinates are not regularly spaced.")
    lat_order = np.argsort(lat)[::-1]
    normalized_lon = ((lon + 180.0) % 360.0) - 180.0
    lon_order = np.argsort(normalized_lon)
    lat = lat[lat_order]
    lon = normalized_lon[lon_order]
    data = data[np.ix_(lat_order, lon_order)]

    # Remove a duplicated cyclic endpoint (commonly 0 and 360 degrees).
    keep = np.ones(lon.size, dtype=bool)
    if lon.size > 1:
        keep[1:] = np.diff(lon) > 1e-8
    if not np.all(keep):
        lon = lon[keep]
        data = data[:, keep]
    if lon.size < 2:
        raise ValueError("Longitude grid collapses after removing duplicated cyclic endpoints.")
    lon_steps = np.diff(lon)
    if not np.all(lon_steps > 0):
        raise ValueError("Longitude coordinates are not strictly increasing after normalization.")
    if not np.allclose(lon_steps, np.median(lon_steps), rtol=1e-3, atol=1e-6):
        raise ValueError("Longitude coordinates are not regularly spaced.")
    return data, lat, lon


def grid_bounds(lat: np.ndarray, lon: np.ndarray) -> dict:
    """Estimate outer pixel edges from regularly spaced coordinate centres."""
    dlat = float(np.median(np.abs(np.diff(lat))))
    dlon = float(np.median(np.diff(lon)))
    north = min(90.0, float(np.max(lat)) + dlat / 2)
    south = max(-90.0, float(np.min(lat)) - dlat / 2)
    west = max(-180.0, float(np.min(lon)) - dlon / 2)
    east = min(180.0, float(np.max(lon)) + dlon / 2)
    return {"west": west, "south": south, "east": east, "north": north}


def _colourize(values: np.ndarray, valid: np.ndarray, vmin: float, vmax: float) -> np.ndarray:
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
        raise ValueError("Invalid rendering range.")
    scaled = np.clip((values - vmin) / (vmax - vmin), 0.0, 1.0)
    position = scaled * (len(SCALAR_STOPS) - 1)
    left = np.floor(position).astype(np.int32)
    right = np.minimum(left + 1, len(SCALAR_STOPS) - 1)
    frac = (position - left)[..., None]
    rgb = SCALAR_STOPS[left] * (1.0 - frac) + SCALAR_STOPS[right] * frac
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    rgba[..., :3] = np.rint(rgb).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 205, 0).astype(np.uint8)
    return rgba


def render_scalar_png(values: np.ndarray, latitudes: np.ndarray, longitudes: np.ndarray,
                      output_path, vmin: float | None = None, vmax: float | None = None) -> dict:
    """Render a scalar field as a transparent RGBA PNG and return geographic metadata."""
    data, lat, lon = normalize_regular_grid(values, latitudes, longitudes)
    valid = np.isfinite(data)
    if not np.any(valid):
        raise ValueError("The selected field contains no valid numeric cells.")
    low = float(np.nanpercentile(data, 2)) if vmin is None else float(vmin)
    high = float(np.nanpercentile(data, 98)) if vmax is None else float(vmax)
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low, high = float(np.nanmin(data)), float(np.nanmax(data))
        if high <= low:
            high = low + 1.0
    safe = np.where(valid, data, low)
    rgba = _colourize(safe, valid, low, high)
    Image.fromarray(rgba, mode="RGBA").save(output_path, format="PNG", optimize=True)
    return {
        "bounds": grid_bounds(lat, lon),
        "width": int(lon.size),
        "height": int(lat.size),
        "value_min": low,
        "value_max": high,
        "valid_cells": int(valid.sum()),
        "missing_cells": int((~valid).sum()),
        "coordinate_order": "north_to_south/west_to_east",
        "longitude_convention": "-180_to_180",
    }


def render_wind_speed_png(u: np.ndarray, v: np.ndarray, latitudes: np.ndarray,
                          longitudes: np.ndarray, output_path) -> dict:
    """Render wind speed from U/V components as a transparent map overlay."""
    if np.asarray(u).shape != np.asarray(v).shape:
        raise ValueError("U and V wind arrays must have identical shapes.")
    speed = np.hypot(np.asarray(u, dtype=np.float32), np.asarray(v, dtype=np.float32))
    return render_scalar_png(speed, latitudes, longitudes, output_path, 0.0, 40.0)
