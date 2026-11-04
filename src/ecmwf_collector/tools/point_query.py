"""Gridpoint and bilinear sampling for map-layer scientific data."""
from __future__ import annotations

from pathlib import Path
import numpy as np


def _bracket(axis: np.ndarray, value: float):
    """Return lower/upper indices and interpolation fraction on an ascending axis."""
    if value < axis[0] - 1e-8 or value > axis[-1] + 1e-8:
        raise ValueError("The clicked location is outside the data grid coverage.")
    if value <= axis[0]:
        return 0, 0, 0.0
    if value >= axis[-1]:
        last = axis.size - 1
        return last, last, 0.0
    upper = int(np.searchsorted(axis, value, side="right"))
    lower = upper - 1
    return lower, upper, float((value - axis[lower]) / (axis[upper] - axis[lower]))


def sample_npz(path: Path, latitude: float, longitude: float, method: str = "nearest") -> dict:
    """Sample a regular grid using nearest-cell or strict four-corner bilinear interpolation.

    Bilinear sampling is only returned when all four surrounding source cells are finite.
    It never extrapolates beyond the grid's outer cell centres.
    """
    if method not in {"nearest", "bilinear"}:
        raise ValueError("Sampling method must be 'nearest' or 'bilinear'.")
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != ".npz":
        raise FileNotFoundError("Scientific data layer was not found.")
    if not (-90.0 <= latitude <= 90.0) or not np.isfinite(longitude):
        raise ValueError("Coordinates are outside valid geographic ranges.")
    with np.load(path, allow_pickle=False) as archive:
        values = np.asarray(archive["values"], dtype=np.float32)
        latitudes = np.asarray(archive["latitudes"], dtype=np.float64)
        longitudes = np.asarray(archive["longitudes"], dtype=np.float64)
    if values.ndim != 2 or latitudes.ndim != 1 or longitudes.ndim != 1:
        raise ValueError("Scientific layer must contain a 2-D field and 1-D coordinates.")
    if values.shape != (latitudes.size, longitudes.size):
        raise ValueError("Scientific layer has inconsistent grid dimensions.")
    if latitudes.size < 2 or longitudes.size < 2:
        raise ValueError("At least a 2x2 1-D latitude/longitude grid is required.")
    if not np.all(np.isfinite(latitudes)) or not np.all(np.isfinite(longitudes)):
        raise ValueError("Grid coordinates contain non-finite values.")
    if np.any(np.abs(latitudes) > 90.0):
        raise ValueError("Grid latitude coordinates are outside -90..90 degrees.")

    lat_diffs = np.diff(latitudes)
    unwrapped_longitudes = np.rad2deg(np.unwrap(np.deg2rad(longitudes)))
    lon_diffs = np.diff(unwrapped_longitudes)
    if not (np.all(lat_diffs > 0) or np.all(lat_diffs < 0)):
        raise ValueError("Latitude coordinates are not strictly monotonic.")
    if not (np.all(lon_diffs > 0) or np.all(lon_diffs < 0)):
        raise ValueError("Longitude coordinates are not strictly monotonic after dateline unwrapping.")
    if not np.allclose(np.abs(lat_diffs), np.median(np.abs(lat_diffs)), rtol=1e-3, atol=1e-6):
        raise ValueError("Latitude coordinates are not regularly spaced.")
    if not np.allclose(np.abs(lon_diffs), np.median(np.abs(lon_diffs)), rtol=1e-3, atol=1e-6):
        raise ValueError("Longitude coordinates are not regularly spaced.")

    query_longitude = longitude + 360.0 * round(
        (float(np.mean(unwrapped_longitudes)) - longitude) / 360.0
    )
    if method == "nearest":
        lat_delta = np.abs(latitudes - latitude)
        lon_delta = np.abs(unwrapped_longitudes - query_longitude)
        row, col = int(np.argmin(lat_delta)), int(np.argmin(lon_delta))
        if (lat_delta[row] > np.median(np.abs(lat_diffs)) / 2.0 + 1e-6
                or lon_delta[col] > np.median(np.abs(lon_diffs)) / 2.0 + 1e-6):
            raise ValueError("The clicked location is outside the data grid coverage.")
        value = float(values[row, col])
        result = {"valid": bool(np.isfinite(value)), "latitude": float(latitudes[row]),
                  "longitude": float(longitudes[col]),
                  "value": value if np.isfinite(value) else None, "method": "nearest"}
        if not result["valid"]:
            result["message"] = "Nearest grid cell contains missing data."
        return result

    lat_axis, lon_axis, grid = latitudes, unwrapped_longitudes, values
    if lat_axis[0] > lat_axis[-1]:
        lat_axis, grid = lat_axis[::-1], grid[::-1, :]
    if lon_axis[0] > lon_axis[-1]:
        lon_axis, grid = lon_axis[::-1], grid[:, ::-1]
    r0, r1, fy = _bracket(lat_axis, latitude)
    c0, c1, fx = _bracket(lon_axis, query_longitude)
    corners = np.asarray([grid[r0, c0], grid[r0, c1], grid[r1, c0], grid[r1, c1]])
    if not np.all(np.isfinite(corners)):
        return {"valid": False, "latitude": float(latitude), "longitude": float(longitude),
                "value": None, "method": "bilinear",
                "message": "Bilinear interpolation requires four valid surrounding grid cells."}
    top = float(grid[r0, c0]) * (1.0 - fx) + float(grid[r0, c1]) * fx
    bottom = float(grid[r1, c0]) * (1.0 - fx) + float(grid[r1, c1]) * fx
    return {"valid": True, "latitude": float(latitude), "longitude": float(longitude),
            "value": top * (1.0 - fy) + bottom * fy, "method": "bilinear"}
