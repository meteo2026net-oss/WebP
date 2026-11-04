"""Geographic normalization and Web-Mercator raster rendering helpers."""
from __future__ import annotations

import numpy as np
from PIL import Image

MAX_MERCATOR_LAT = 85.05112878
SCALAR_STOPS = np.array([
    [35, 45, 110], [45, 95, 170], [45, 155, 190], [75, 185, 120],
    [205, 205, 65], [235, 145, 45], [195, 65, 55], [245, 235, 225],
], dtype=np.float32)


def _regular_steps(values: np.ndarray) -> bool:
    steps = np.diff(values)
    return bool(
        steps.size
        and np.all(steps > 0)
        and np.allclose(steps, np.median(steps), rtol=1e-3, atol=1e-6)
    )


def normalize_regular_grid(values: np.ndarray, latitudes: np.ndarray, longitudes: np.ndarray):
    """Return data north-to-south and west-to-east, unwrapping grids at ±180°."""
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
    if np.any(np.abs(lat) > 90.0):
        raise ValueError("Latitude coordinates must be within -90..90 degrees.")
    lat_diff = np.diff(lat)
    if not (np.all(lat_diff > 0) or np.all(lat_diff < 0)):
        raise ValueError("Latitude coordinates must be strictly monotonic without duplicates.")
    lat_steps = np.abs(lat_diff)
    if not np.allclose(lat_steps, np.median(lat_steps), rtol=1e-3, atol=1e-6):
        raise ValueError("Latitude coordinates are not regularly spaced.")

    lat_order = np.argsort(lat)[::-1]
    normalized_lon = ((lon + 180.0) % 360.0) - 180.0
    lon_order = np.argsort(normalized_lon)
    ordered_lon = normalized_lon[lon_order]
    ordered_data = data[np.ix_(lat_order, lon_order)]

    # Prefer the canonical -180..180 ordering for ordinary grids. If sorting
    # across the antimeridian creates a false 300+ degree gap, retain the
    # original geographic sequence and unwrap it into one continuous interval.
    keep = np.ones(ordered_lon.size, dtype=bool)
    if ordered_lon.size > 1:
        keep[1:] = np.diff(ordered_lon) > 1e-8
    canonical_lon = ordered_lon[keep]
    canonical_data = ordered_data[:, keep]

    if canonical_lon.size >= 2 and _regular_steps(canonical_lon):
        lon, data = canonical_lon, canonical_data
        longitude_convention = "-180_to_180"
    else:
        unwrapped = np.rad2deg(np.unwrap(np.deg2rad(lon)))
        unwrapped_diff = np.diff(unwrapped)
        if np.all(unwrapped_diff < 0):
            unwrapped = unwrapped[::-1]
            ordered_indices = np.arange(lon.size - 1, -1, -1)
        elif np.all(unwrapped_diff > 0):
            ordered_indices = np.arange(lon.size)
        else:
            raise ValueError("Longitude coordinates must be monotonic after antimeridian unwrapping.")
        lon = unwrapped
        data = data[np.ix_(lat_order, ordered_indices)]
        # Remove a repeated cyclic endpoint (for example 180° and -180°).
        if lon.size > 2 and np.isclose(lon[-1] - lon[0], 360.0, atol=1e-6):
            lon, data = lon[:-1], data[:, :-1]
        if lon.size < 2 or not _regular_steps(lon):
            raise ValueError("Longitude coordinates are not regularly spaced after antimeridian unwrapping.")
        # Keep the interval near the conventional world copy while allowing
        # east > 180 or west < -180 when the grid genuinely crosses the seam.
        center = (float(lon[0]) + float(lon[-1])) / 2.0
        if center > 180.0:
            shift = 360.0 * np.floor((center + 180.0) / 360.0)
        elif center < -180.0:
            shift = 360.0 * np.ceil((center - 180.0) / 360.0)
        else:
            shift = 0.0
        lon = lon - shift
        longitude_convention = "continuous_unwrapped"

    if lon.size < 2:
        raise ValueError("Longitude grid collapses after removing duplicated cyclic endpoints.")
    return data, lat[lat_order], lon, longitude_convention


def _mercator_y(latitude_degrees: np.ndarray) -> np.ndarray:
    lat = np.clip(np.deg2rad(latitude_degrees), -np.deg2rad(MAX_MERCATOR_LAT), np.deg2rad(MAX_MERCATOR_LAT))
    return np.log(np.tan(np.pi / 4.0 + lat / 2.0))


def _inverse_mercator_y(y: np.ndarray) -> np.ndarray:
    return np.rad2deg(2.0 * np.arctan(np.exp(y)) - np.pi / 2.0)


def grid_bounds(lat: np.ndarray, lon: np.ndarray) -> dict:
    """Estimate pixel-edge bounds; preserve unwrapped longitude across ±180°."""
    dlat = float(np.median(np.abs(np.diff(lat))))
    dlon = float(np.median(np.diff(lon)))
    north = min(MAX_MERCATOR_LAT, float(np.max(lat)) + dlat / 2)
    south = max(-MAX_MERCATOR_LAT, float(np.min(lat)) - dlat / 2)
    west = float(np.min(lon)) - dlon / 2
    east = float(np.max(lon)) + dlon / 2
    if north <= south or east <= west:
        raise ValueError("Grid has no visible area inside Web Mercator bounds.")
    return {"west": west, "south": south, "east": east, "north": north}


def _resample_rows_to_web_mercator(data: np.ndarray, lat: np.ndarray, bounds: dict) -> np.ndarray:
    """Resample equally spaced latitude rows to equally spaced EPSG:3857 rows."""
    source_lat = lat[::-1]  # ascending
    source = data[::-1, :]
    north_y = _mercator_y(np.array([bounds["north"]]))[0]
    south_y = _mercator_y(np.array([bounds["south"]]))[0]
    target_y = np.linspace(north_y, south_y, data.shape[0])
    target_lat = _inverse_mercator_y(target_y)
    output = np.full(data.shape, np.nan, dtype=np.float32)
    for row, latitude in enumerate(target_lat):
        hi = int(np.searchsorted(source_lat, latitude, side="left"))
        if hi <= 0:
            lo = hi = 0
        elif hi >= source_lat.size:
            lo = hi = source_lat.size - 1
        else:
            lo = hi - 1
        if lo == hi:
            output[row] = source[lo]
            continue
        fraction = float((latitude - source_lat[lo]) / (source_lat[hi] - source_lat[lo]))
        v0, v1 = source[lo], source[hi]
        valid0, valid1 = np.isfinite(v0), np.isfinite(v1)
        w0 = (1.0 - fraction) * valid0
        w1 = fraction * valid1
        weight = w0 + w1
        numerator = np.where(valid0, v0, 0.0) * w0 + np.where(valid1, v1, 0.0) * w1
        output[row] = np.divide(numerator, weight, out=np.full_like(numerator, np.nan), where=weight > 0)
    return output


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
    """Render a transparent RGBA PNG with rows resampled for Leaflet EPSG:3857."""
    data, lat, lon, longitude_convention = normalize_regular_grid(values, latitudes, longitudes)
    bounds = grid_bounds(lat, lon)
    data = _resample_rows_to_web_mercator(data, lat, bounds)
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
        "bounds": bounds,
        "width": int(lon.size),
        "height": int(lat.size),
        "value_min": low,
        "value_max": high,
        "valid_cells": int(valid.sum()),
        "missing_cells": int((~valid).sum()),
        "coordinate_order": "north_to_south",
        "render_projection": "EPSG:3857",
        "longitude_convention": longitude_convention,
    }


def render_wind_speed_png(u: np.ndarray, v: np.ndarray, latitudes: np.ndarray,
                          longitudes: np.ndarray, output_path) -> dict:
    """Render wind speed from U/V components as a transparent map overlay."""
    if np.asarray(u).shape != np.asarray(v).shape:
        raise ValueError("U and V wind arrays must have identical shapes.")
    speed = np.hypot(np.asarray(u, dtype=np.float32), np.asarray(v, dtype=np.float32))
    return render_scalar_png(speed, latitudes, longitudes, output_path, 0.0, 40.0)
