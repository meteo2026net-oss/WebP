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


def _web_mercator_bounds(west: float, south: float, east: float, north: float) -> dict:
    """Convert projected bounds without normalizing unwrapped longitudes at ±180°."""
    radius = 6378137.0
    return {
        "west": float(np.rad2deg(west / radius)),
        # _inverse_mercator_y expects dimensionless Mercator coordinates,
        # while south/north are projected metres (EPSG:3857).
        "south": float(_inverse_mercator_y(np.asarray([south / radius]))[0]),
        "east": float(np.rad2deg(east / radius)),
        "north": float(_inverse_mercator_y(np.asarray([north / radius]))[0]),
    }


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



def _unwrap_curvilinear_longitudes(longitudes: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Unwrap a regional 2-D longitude mesh and reject ambiguous global spans.

    A single planar triangulation cannot represent a global grid across the
    antimeridian without introducing false connections between opposite edges.
    Until seam-aware tiled rendering is implemented, fail closed when the
    shortest circular longitude interval still exceeds 180 degrees.
    """
    radians = np.deg2rad(longitudes[valid])
    center = float(np.rad2deg(np.arctan2(np.mean(np.sin(radians)),
                                        np.mean(np.cos(radians)))))
    unwrapped = np.full(longitudes.shape, np.nan, dtype=np.float64)
    unwrapped[valid] = center + ((longitudes[valid] - center + 180.0) % 360.0) - 180.0
    span = float(np.max(unwrapped[valid]) - np.min(unwrapped[valid]))
    if span > 180.0 + 1e-6:
        raise ValueError(
            "Curvilinear grids spanning more than 180 degrees of longitude "
            "require seam-aware global rendering and are not supported yet."
        )
    return unwrapped


def _render_curvilinear_scalar_png(values: np.ndarray, latitudes: np.ndarray,
                                    longitudes: np.ndarray, output_path,
                                    vmin: float | None = None,
                                    vmax: float | None = None) -> dict:
    """Reproject a 2-D geolocation grid to a regular Web-Mercator raster.

    This path handles GRIB grids whose latitude/longitude coordinates are 2-D
    (including rotated-pole, Lambert and polar-stereographic grids) without
    guessing projection parameters: the decoder-provided geolocation is used.
    """
    try:
        from scipy.interpolate import griddata
    except ImportError as exc:
        raise RuntimeError(
            "Curvilinear grid rendering requires scipy."
        ) from exc

    data = np.asarray(values, dtype=np.float32)
    lat = np.asarray(latitudes, dtype=np.float64)
    lon = np.asarray(longitudes, dtype=np.float64)
    if lat.ndim != 2 or lon.ndim != 2 or data.shape != lat.shape or data.shape != lon.shape:
        raise ValueError("Curvilinear values, latitude and longitude must be matching 2-D arrays.")
    if min(data.shape) < 2:
        raise ValueError("Curvilinear grids must contain at least 2 rows and 2 columns.")
    geo_valid = np.isfinite(lat) & np.isfinite(lon) & (np.abs(lat) <= 90.0)
    if int(geo_valid.sum()) < 3:
        raise ValueError("At least three valid geolocation coordinates are required.")
    # Missing geolocation is normal outside some projected-grid domains.
    # Ignore those cells rather than rejecting an otherwise usable field.
    # Unwrap around the circular-mean longitude so regional grids near ±180°
    # remain narrow instead of being projected across almost the whole world.
    unwrapped_lon = _unwrap_curvilinear_longitudes(lon, geo_valid)
    lat_for_projection = np.clip(lat, -MAX_MERCATOR_LAT, MAX_MERCATOR_LAT)
    # Apply the spherical Web-Mercator equations directly. PROJ may normalize
    # longitudes outside [-180, 180] depending on its version/configuration,
    # which would collapse a regional grid crossing the antimeridian.
    earth_radius = 6378137.0
    x = earth_radius * np.deg2rad(unwrapped_lon)
    y = earth_radius * _mercator_y(lat_for_projection)
    projected_geo_valid = geo_valid & np.isfinite(x) & np.isfinite(y)
    valid = np.isfinite(data) & projected_geo_valid
    if int(valid.sum()) < 3:
        raise ValueError("At least three valid geolocated data cells are required for reprojection.")
    if np.unique(np.column_stack((x[valid], y[valid])), axis=0).shape[0] < 3:
        raise ValueError("Curvilinear grid has fewer than three distinct valid projected cells.")

    west, east = float(np.min(x[projected_geo_valid])), float(np.max(x[projected_geo_valid]))
    south, north = float(np.min(y[projected_geo_valid])), float(np.max(y[projected_geo_valid]))
    if not (east > west and north > south):
        raise ValueError("Curvilinear grid has no two-dimensional map extent.")
    height, width = data.shape
    target_x = np.linspace(west, east, width)
    target_y = np.linspace(north, south, height)
    mesh_x, mesh_y = np.meshgrid(target_x, target_y)
    points = np.column_stack((x[valid], y[valid]))
    try:
        sampled = griddata(points, data[valid], (mesh_x, mesh_y), method="linear")
    except Exception as exc:
        raise ValueError(
            "Curvilinear geolocation cannot form a valid 2-D interpolation mesh."
        ) from exc
    if not np.any(np.isfinite(sampled)):
        raise ValueError("Curvilinear reprojection produced no valid raster cells.")

    low = float(np.nanpercentile(sampled, 2)) if vmin is None else float(vmin)
    high = float(np.nanpercentile(sampled, 98)) if vmax is None else float(vmax)
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low, high = float(np.nanmin(sampled)), float(np.nanmax(sampled))
        if high <= low:
            high = low + 1.0
    rgba = _colourize(np.where(np.isfinite(sampled), sampled, low),
                     np.isfinite(sampled), low, high)
    Image.fromarray(rgba, mode="RGBA").save(output_path, format="PNG", optimize=True)

    bounds = _web_mercator_bounds(west, south, east, north)
    return {
        "bounds": bounds,
        "width": int(width), "height": int(height),
        "value_min": low, "value_max": high,
        "valid_cells": int(np.isfinite(sampled).sum()),
        "missing_cells": int((~np.isfinite(sampled)).sum()),
        "coordinate_order": "north_to_south",
        "render_projection": "EPSG:3857",
        "longitude_convention": "curvilinear_unwrapped",
        "source_grid_type": "curvilinear_geolocation",
        "resampling": "linear",
    }


def render_scalar_png(values: np.ndarray, latitudes: np.ndarray, longitudes: np.ndarray,
                      output_path, vmin: float | None = None, vmax: float | None = None) -> dict:
    """Render a transparent RGBA PNG with rows resampled for Leaflet EPSG:3857."""
    if np.asarray(latitudes).ndim == 2 or np.asarray(longitudes).ndim == 2:
        return _render_curvilinear_scalar_png(values, latitudes, longitudes, output_path, vmin, vmax)
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


def render_direction_png(direction_degrees: np.ndarray, latitudes: np.ndarray,
                         longitudes: np.ndarray, output_path,
                         resultant_threshold: float = 1e-3) -> dict:
    """Render meteorological FROM bearings with cyclic HSV colours.

    Interpolation is performed on sine/cosine components, never on raw
    degree values, so bearings around 0/360 degrees remain continuous.
    """
    direction = np.asarray(direction_degrees, dtype=np.float32)
    if not 0.0 <= resultant_threshold < 1.0:
        raise ValueError("resultant_threshold must be in [0, 1).")
    lat = np.asarray(latitudes, dtype=np.float64)
    lon = np.asarray(longitudes, dtype=np.float64)
    if direction.shape != lat.shape if lat.ndim == 2 else direction.shape != (lat.size, lon.size):
        raise ValueError("Direction values do not match latitude/longitude grid.")
    valid = np.isfinite(direction)
    if not np.any(valid):
        raise ValueError("The selected direction field contains no valid bearings.")
    radians = np.deg2rad(np.mod(direction, 360.0))
    sine = np.where(valid, np.sin(radians), np.nan).astype(np.float32)
    cosine = np.where(valid, np.cos(radians), np.nan).astype(np.float32)

    if lat.ndim == 2 or lon.ndim == 2:
        try:
            from scipy.interpolate import griddata
        except ImportError as exc:
            raise RuntimeError("Curvilinear direction rendering requires scipy.") from exc
        if lat.ndim != 2 or lon.ndim != 2 or lat.shape != lon.shape or direction.shape != lat.shape:
            raise ValueError("Curvilinear direction and geolocation arrays must have matching 2-D shapes.")
        geo = np.isfinite(lat) & np.isfinite(lon) & (np.abs(lat) <= 90)
        usable = geo & valid
        if int(usable.sum()) < 3:
            raise ValueError("At least three valid direction cells with geolocation are required.")
        unwrapped = _unwrap_curvilinear_longitudes(lon, geo)
        # Keep unwrapped longitude values continuous beyond ±180°.
        earth_radius = 6378137.0
        x = earth_radius * np.deg2rad(unwrapped)
        y = earth_radius * _mercator_y(np.clip(lat, -MAX_MERCATOR_LAT, MAX_MERCATOR_LAT))
        projected = geo & np.isfinite(x) & np.isfinite(y)
        usable = usable & projected
        if int(usable.sum()) < 3:
            raise ValueError("At least three valid projected direction cells are required.")
        if np.unique(np.column_stack((x[usable], y[usable])), axis=0).shape[0] < 3:
            raise ValueError("Curvilinear direction grid has fewer than three distinct projected cells.")
        west, east = float(np.min(x[projected])), float(np.max(x[projected]))
        south, north = float(np.min(y[projected])), float(np.max(y[projected]))
        if east <= west or north <= south:
            raise ValueError("Curvilinear direction grid has no 2-D projected extent.")
        height, width = direction.shape
        tx, ty = np.meshgrid(np.linspace(west, east, width), np.linspace(north, south, height))
        points = np.column_stack((x[usable], y[usable]))
        try:
            sampled_sin = griddata(points, sine[usable], (tx, ty), method="linear")
            sampled_cos = griddata(points, cosine[usable], (tx, ty), method="linear")
        except Exception as exc:
            raise ValueError("Curvilinear direction grid cannot form an interpolation mesh.") from exc
        bounds = _web_mercator_bounds(west, south, east, north)
        convention = "curvilinear_unwrapped"
    else:
        sine_grid, out_lat, out_lon, convention = normalize_regular_grid(sine, lat, lon)
        cosine_grid, _, _, _ = normalize_regular_grid(cosine, lat, lon)
        bounds = grid_bounds(out_lat, out_lon)
        sampled_sin = _resample_rows_to_web_mercator(sine_grid, out_lat, bounds)
        sampled_cos = _resample_rows_to_web_mercator(cosine_grid, out_lat, bounds)
        height, width = sampled_sin.shape

    magnitude = np.hypot(sampled_sin, sampled_cos)
    usable = np.isfinite(magnitude) & (magnitude >= resultant_threshold)
    angle = np.mod(np.rad2deg(np.arctan2(sampled_sin, sampled_cos)), 360.0)
    hue = np.zeros(angle.shape, dtype=np.uint8)
    hue[usable] = np.rint(angle[usable] / 360.0 * 255.0).astype(np.uint8)
    hsv = np.zeros((*angle.shape, 3), dtype=np.uint8)
    hsv[..., 0] = hue
    hsv[..., 1] = 255
    hsv[..., 2] = 255
    rgba = np.asarray(Image.fromarray(hsv, mode="HSV").convert("RGBA")).copy()
    rgba[..., 3] = np.where(usable, 220, 0).astype(np.uint8)
    Image.fromarray(rgba, mode="RGBA").save(output_path, format="PNG", optimize=True)
    return {
        "bounds": bounds, "width": int(width), "height": int(height),
        "value_min": 0.0, "value_max": 360.0,
        "valid_cells": int(usable.sum()), "missing_cells": int((~usable).sum()),
        "coordinate_order": "north_to_south", "render_projection": "EPSG:3857",
        "longitude_convention": convention, "resampling": "circular_sine_cosine",
        "color_encoding": "HSV_hue_bearing_degrees_clockwise_from_true_north",
        "resultant_threshold": float(resultant_threshold),
    }
