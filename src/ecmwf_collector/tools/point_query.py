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
        row_steps, column_steps = [], []
        for nr in (row - 1, row + 1):
            if 0 <= nr < distance.shape[0] and geo_valid[nr, col]:
                step = _great_circle_distance_degrees(
                    latitudes[row, col], longitudes[row, col],
                    latitudes[nr, col], longitudes[nr, col]
                )
                if np.isfinite(step) and step > 0:
                    row_steps.append(float(step))
        for nc in (col - 1, col + 1):
            if 0 <= nc < distance.shape[1] and geo_valid[row, nc]:
                step = _great_circle_distance_degrees(
                    latitudes[row, col], longitudes[row, col],
                    latitudes[row, nc], longitudes[row, nc]
                )
                if np.isfinite(step) and step > 0:
                    column_steps.append(float(step))
        local_steps = row_steps + column_steps
        if row_steps and column_steps:
            coverage_radius = 0.5 * np.hypot(
                float(np.median(row_steps)), float(np.median(column_steps))
            )
        elif local_steps:
            coverage_radius = 0.5 * float(np.median(local_steps))
        else:
            coverage_radius = None
        if coverage_radius is None:
            raise ValueError(
                "The nearest curvilinear cell has no valid local neighbours; grid coverage cannot be established."
            )
        if distance[row, col] > coverage_radius:
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
    longitude_step = float(np.median(np.abs(np.diff(lon_axis))))
    longitude_span = float(lon_axis[-1] - lon_axis[0])
    cyclic_tolerance = max(1e-6, longitude_step * 1e-6)
    has_duplicate_cyclic_endpoint = np.isclose(
        longitude_span, 360.0, rtol=0.0, atol=cyclic_tolerance
    )
    is_cyclic_global_grid = has_duplicate_cyclic_endpoint or np.isclose(
        longitude_span + longitude_step, 360.0,
        rtol=0.0, atol=cyclic_tolerance,
    )
    if has_duplicate_cyclic_endpoint:
        # A repeated 360-degree endpoint represents the same meridian as the
        # first column. Drop only that duplicate before seam interpolation.
        lon_axis = lon_axis[:-1]
        grid = grid[:, :-1]
    if is_cyclic_global_grid:
        wrapped_longitude = float(
            lon_axis[0] + ((query_longitude - lon_axis[0]) % 360.0)
        )
        if wrapped_longitude > lon_axis[-1] + 1e-8:
            # Interpolate across the cyclic seam using the first column as its
            # next-world copy, rather than rejecting a valid global query.
            c0, c1 = lon_axis.size - 1, 0
            seam_width = float(lon_axis[0] + 360.0 - lon_axis[-1])
            fx = float((wrapped_longitude - lon_axis[-1]) / seam_width)
        else:
            c0, c1, fx = _bracket(lon_axis, wrapped_longitude)
    else:
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
