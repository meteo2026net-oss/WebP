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
    if latitudes.ndim != 1 or longitudes.ndim != 1 or not latitudes.size or not longitudes.size:
        raise ValueError("Only 1-D latitude/longitude grids can be sampled.")
    row = int(np.argmin(np.abs(latitudes - latitude)))
    lon_delta = (longitudes - longitude + 180.0) % 360.0 - 180.0
    col = int(np.argmin(np.abs(lon_delta)))
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
