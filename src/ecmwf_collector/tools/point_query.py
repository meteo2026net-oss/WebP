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
    lat_step = float(np.median(np.abs(np.diff(latitudes))))
    lon_step = float(np.median(np.abs(np.diff(longitudes))))
    lat_delta = np.abs(latitudes - latitude)
    lon_delta = np.abs((longitudes - longitude + 180.0) % 360.0 - 180.0)
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
