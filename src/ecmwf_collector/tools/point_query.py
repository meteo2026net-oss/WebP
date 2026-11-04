"""Gridpoint and bilinear sampling for map-layer scientific data."""
from __future__ import annotations

from pathlib import Path
import numpy as np


def _great_circle_distance_degrees(lat1, lon1, lat2, lon2):
    """Return spherical angular distance in degrees with stable dateline wrapping."""
    lat1 = np.deg2rad(np.asarray(lat1, dtype=np.float64))
    lat2 = np.deg2rad(np.asarray(lat2, dtype=np.float64))
    dlat = lat2 - lat1
    dlon = np.deg2rad((np.asarray(lon2, dtype=np.float64)
                       - np.asarray(lon1, dtype=np.float64) + 180.0) % 360.0 - 180.0)
    hav = (np.sin(dlat / 2.0) ** 2
           + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2)
    return np.rad2deg(2.0 * np.arcsin(np.sqrt(np.clip(hav, 0.0, 1.0))))


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
    if values.ndim != 2 or latitudes.ndim != longitudes.ndim or latitudes.ndim not in (1, 2):
        raise ValueError("Scientific layer must contain a 2-D field and matching 1-D or 2-D geolocation.")
    expected_shape = ((latitudes.size, longitudes.size) if latitudes.ndim == 1
                      else latitudes.shape)
    if values.shape != expected_shape or latitudes.shape != longitudes.shape:
        raise ValueError("Scientific layer has inconsistent grid dimensions.")
    if min(latitudes.shape) < 2:
        raise ValueError("At least a 2x2 latitude/longitude grid is required.")
    if latitudes.ndim == 1:
        if not np.all(np.isfinite(latitudes)) or not np.all(np.isfinite(longitudes)):
            raise ValueError("Grid coordinates contain non-finite values.")
        if np.any(np.abs(latitudes) > 90.0):
            raise ValueError("Grid latitude coordinates are outside -90..90 degrees.")
    else:
        geo_valid = (np.isfinite(latitudes) & np.isfinite(longitudes)
                     & (np.abs(latitudes) <= 90.0))
        if int(geo_valid.sum()) < 3:
            raise ValueError("Curvilinear grid has fewer than three valid geolocation cells.")

    if latitudes.ndim == 2:
        if method == "bilinear":
            raise ValueError("Bilinear sampling is currently limited to regular 1-D latitude/longitude grids.")
        distance = _great_circle_distance_degrees(
            latitude, longitude, latitudes, longitudes
        )
        distance[~geo_valid] = np.inf
        row, col = np.unravel_index(int(np.argmin(distance)), distance.shape)
        if not np.isfinite(distance[row, col]):
            raise ValueError("Curvilinear grid has no valid geolocation cells.")
        neighbour_steps = []
        if distance.shape[0] > 1:
            valid_pairs = geo_valid[:-1, :] & geo_valid[1:, :]
            steps = _great_circle_distance_degrees(
                latitudes[:-1, :], longitudes[:-1, :],
                latitudes[1:, :], longitudes[1:, :]
            )
            neighbour_steps.extend(steps[valid_pairs & np.isfinite(steps) & (steps > 0)].tolist())
        if distance.shape[1] > 1:
            valid_pairs = geo_valid[:, :-1] & geo_valid[:, 1:]
            steps = _great_circle_distance_degrees(
                latitudes[:, :-1], longitudes[:, :-1],
                latitudes[:, 1:], longitudes[:, 1:]
            )
            neighbour_steps.extend(steps[valid_pairs & np.isfinite(steps) & (steps > 0)].tolist())
        if neighbour_steps and distance[row, col] > float(np.median(neighbour_steps)) * 0.8:
            raise ValueError("The clicked location is outside the data grid coverage.")
        value = float(values[row, col])
        result = {"valid": bool(np.isfinite(value)),
                  "latitude": float(latitudes[row, col]),
                  "longitude": float(longitudes[row, col]),
                  "value": value if np.isfinite(value) else None,
                  "method": "nearest", "grid_type": "curvilinear"}
        if not result["valid"]:
            result["message"] = "Nearest grid cell contains missing data."
        return result

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
