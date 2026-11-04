"""Nearest-gridpoint sampling for map-layer scientific data."""
from __future__ import annotations

from pathlib import Path
import numpy as np


def sample_npz(path: Path, latitude: float, longitude: float) -> dict:
    """Return the nearest valid grid cell from a converter-generated NPZ file."""
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != ".npz":
        raise FileNotFoundError("Scientific data layer was not found.")
    if not (-90.0 <= latitude <= 90.0) or not np.isfinite(longitude):
        raise ValueError("Coordinates are outside valid geographic ranges.")
    with np.load(path, allow_pickle=False) as archive:
        values = np.asarray(archive["values"], dtype=np.float32)
        latitudes = np.asarray(archive["latitudes"], dtype=np.float64)
        longitudes = np.asarray(archive["longitudes"], dtype=np.float64)
    if values.ndim != 2 or values.shape != (latitudes.size, longitudes.size):
        raise ValueError("Scientific layer has inconsistent grid dimensions.")
    if latitudes.ndim != 1 or longitudes.ndim != 1 or latitudes.size < 2 or longitudes.size < 2:
        raise ValueError("At least a 2x2 1-D latitude/longitude grid is required.")
    if not np.all(np.isfinite(latitudes)) or not np.all(np.isfinite(longitudes)):
        raise ValueError("Grid coordinates contain non-finite values.")
    if np.any(np.abs(latitudes) > 90.0):
        raise ValueError("Grid latitude coordinates are outside -90..90 degrees.")
    lat_diffs = np.diff(latitudes)
    # Unwrap longitudes so a regular grid crossing 180E/180W remains a small step.
    unwrapped_longitudes = np.rad2deg(np.unwrap(np.deg2rad(longitudes)))
    lon_diffs = np.diff(unwrapped_longitudes)
    if not (np.all(lat_diffs > 0) or np.all(lat_diffs < 0)):
        raise ValueError("Latitude coordinates are not strictly monotonic.")
    if not (np.all(lon_diffs > 0) or np.all(lon_diffs < 0)):
        raise ValueError("Longitude coordinates are not strictly monotonic after dateline unwrapping.")
    lat_steps, lon_steps = np.abs(lat_diffs), np.abs(lon_diffs)
    if not np.allclose(lat_steps, np.median(lat_steps), rtol=1e-3, atol=1e-6):
        raise ValueError("Latitude coordinates are not regularly spaced.")
    if not np.allclose(lon_steps, np.median(lon_steps), rtol=1e-3, atol=1e-6):
        raise ValueError("Longitude coordinates are not regularly spaced.")
    lat_step = float(np.median(lat_steps))
    lon_step = float(np.median(lon_steps))
    lat_delta = np.abs(latitudes - latitude)
    query_longitude = longitude + 360.0 * round((float(np.mean(unwrapped_longitudes)) - longitude) / 360.0)
    lon_delta = np.abs(unwrapped_longitudes - query_longitude)
    row = int(np.argmin(lat_delta))
    col = int(np.argmin(lon_delta))
    if lat_delta[row] > lat_step / 2.0 + 1e-6 or lon_delta[col] > lon_step / 2.0 + 1e-6:
        raise ValueError("The clicked location is outside the data grid coverage.")
    value = float(values[row, col])
    if not np.isfinite(value):
        return {
            "valid": False, "latitude": float(latitudes[row]),
            "longitude": float(longitudes[col]), "value": None,
            "message": "Nearest grid cell contains missing data."
        }
    return {
        "valid": True, "latitude": float(latitudes[row]),
        "longitude": float(longitudes[col]), "value": value,
    }
