"""Decode and safely align selected GEFS GRIB2 fields across ensemble members."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np

from ecmwf_collector.gefs_grib import load_gefs_member_metadata


class GefsGribDecodeError(ValueError):
    """Raised when a GRIB field cannot be decoded or compared safely."""


@dataclass(frozen=True)
class DecodedGefsField:
    values: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    units: str
    initialization_time: str
    valid_time: str
    forecast_hour: int


def _open_cfgrib_datasets(path: Path):
    try:
        import cfgrib
    except ImportError as exc:
        raise GefsGribDecodeError(
            "cfgrib and its ecCodes backend are required to decode GRIB2 files"
        ) from exc
    try:
        return cfgrib.open_datasets(str(path), backend_kwargs={"indexpath": ""})
    except Exception as exc:
        raise GefsGribDecodeError(f"cfgrib could not decode {path.name}: {exc}") from exc


def _coord_value(dataset, name: str):
    if name not in dataset.coords:
        raise GefsGribDecodeError(f"decoded GRIB field is missing {name} coordinate")
    value = np.asarray(dataset.coords[name].values)
    if value.size != 1:
        raise GefsGribDecodeError(f"expected one {name} value, received {value.size}")
    return value.reshape(-1)[0]


def _as_utc_string(value) -> str:
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            raise GefsGribDecodeError("GRIB time coordinate is NaT")
        value = np.datetime_as_string(value, unit="s")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise GefsGribDecodeError(f"invalid GRIB time coordinate: {text}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _step_hours(value) -> int:
    if isinstance(value, np.timedelta64):
        seconds = float(value / np.timedelta64(1, "s"))
    elif hasattr(value, "total_seconds"):
        seconds = float(value.total_seconds())
    else:
        try:
            hours = float(value)
        except (TypeError, ValueError) as exc:
            raise GefsGribDecodeError(f"invalid GRIB forecast step: {value}") from exc
        if not np.isfinite(hours) or not hours.is_integer():
            raise GefsGribDecodeError(f"forecast step must be a whole number of hours: {value}")
        return int(hours)
    hours = seconds / 3600.0
    if not np.isfinite(hours) or not hours.is_integer():
        raise GefsGribDecodeError(f"forecast step must be a whole number of hours: {value}")
    return int(hours)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise GefsGribDecodeError(f"invalid GRIB forecast step: {value}") from exc


def decode_gefs_grib_field(
    grib_path: str | Path, *, short_name: str, type_of_level: str, level: float
) -> DecodedGefsField:
    """Decode one exact GRIB field; caller supplies ecCodes shortName and level keys."""
    path = Path(grib_path)
    datasets = _open_cfgrib_datasets(path)
    try:
        matches = []
        for dataset in datasets:
            for variable in dataset.data_vars.values():
                attrs = variable.attrs
                if (attrs.get("GRIB_shortName") == short_name
                    and attrs.get("GRIB_typeOfLevel") == type_of_level
                    and float(attrs.get("GRIB_level", float("nan"))) == float(level)):
                    matches.append((dataset, variable))
        if len(matches) != 1:
            raise GefsGribDecodeError(
                f"expected exactly one {short_name}/{type_of_level}/{level} field in {path.name}; found {len(matches)}"
            )
        dataset, variable = matches[0]
        latitude = np.asarray(dataset.coords["latitude"].values, dtype=np.float64)
        longitude = np.asarray(dataset.coords["longitude"].values, dtype=np.float64)
        values = np.asarray(variable.values, dtype=np.float64)
        if latitude.size == 0 or longitude.size == 0 or values.size == 0:
            raise GefsGribDecodeError(f"decoded field is empty: {path.name}")
        if values.ndim != 2:
            raise GefsGribDecodeError(
                f"expected a two-dimensional horizontal field in {path.name}; received shape {values.shape}"
            )
        if not np.all(np.isfinite(latitude)) or not np.all(np.isfinite(longitude)):
            raise GefsGribDecodeError(f"latitude/longitude coordinates contain non-finite values: {path.name}")
        if latitude.ndim == 1 and longitude.ndim == 1:
            expected_grid_shape = (latitude.size, longitude.size)
        elif latitude.shape == longitude.shape and latitude.ndim == 2:
            expected_grid_shape = latitude.shape
        else:
            raise GefsGribDecodeError(
                f"unsupported latitude/longitude coordinate shapes in {path.name}: {latitude.shape}/{longitude.shape}"
            )
        if values.shape[-2:] != expected_grid_shape:
            raise GefsGribDecodeError(
                f"field/grid shape mismatch in {path.name}: {values.shape} vs {expected_grid_shape}"
            )
        units = str(variable.attrs.get("units") or "").strip()
        if not units:
            raise GefsGribDecodeError(f"decoded field has no units: {path.name}")
        initialization = _as_utc_string(_coord_value(dataset, "time"))
        valid = _as_utc_string(_coord_value(dataset, "valid_time"))
        forecast_hour = _step_hours(_coord_value(dataset, "step"))
        return DecodedGefsField(values, latitude, longitude, units, initialization, valid, forecast_hour)
    except KeyError as exc:
        raise GefsGribDecodeError(f"decoded GRIB field lacks required coordinate/metadata: {exc}") from exc
    finally:
        for dataset in datasets:
            close = getattr(dataset, "close", None)
            if callable(close):
                close()


def decode_gefs_ensemble_fields(
    grib_paths: Iterable[str | Path], *, short_name: str, type_of_level: str, level: float,
    minimum_members: int = 2,
) -> tuple[dict[str, np.ndarray], dict]:
    """Decode and align members only when provenance, grid, units and times agree."""
    paths = [Path(path) for path in grib_paths]
    metadata = load_gefs_member_metadata(paths, minimum_members=minimum_members)
    decoded = {}
    reference = None
    reference_member = None
    for path in paths:
        sidecar_path = path.with_name(path.stem + ".source.json")
        import json
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        member = str(sidecar["member"])
        field = decode_gefs_grib_field(
            path, short_name=short_name, type_of_level=type_of_level, level=level
        )
        expected = (
            _as_utc_string(sidecar["run"]),
            _as_utc_string(sidecar["valid_time"]),
            int(sidecar["forecast_hour"]),
        )
        actual = (field.initialization_time, field.valid_time, field.forecast_hour)
        if actual != expected:
            raise GefsGribDecodeError(
                f"{member} GRIB time identity does not match its sidecar: expected {expected}, received {actual}"
            )
        if reference is None:
            reference, reference_member = field, member
        else:
            if field.values.shape != reference.values.shape:
                raise GefsGribDecodeError(f"{member} grid shape differs from {reference_member}")
            if not np.array_equal(field.latitude, reference.latitude):
                raise GefsGribDecodeError(f"{member} latitude grid differs from {reference_member}")
            if not np.array_equal(field.longitude, reference.longitude):
                raise GefsGribDecodeError(f"{member} longitude grid differs from {reference_member}")
            if field.units != reference.units:
                raise GefsGribDecodeError(f"{member} units {field.units!r} differ from {reference.units!r}")
            if (field.initialization_time, field.valid_time, field.forecast_hour) != (
                reference.initialization_time, reference.valid_time, reference.forecast_hour
            ):
                raise GefsGribDecodeError(f"{member} GRIB time coordinates differ from {reference_member}")
        decoded[member] = field.values
    return decoded, {
        "units": reference.units,
        "latitude": reference.latitude,
        "longitude": reference.longitude,
        "initialization_time": reference.initialization_time,
        "valid_time": reference.valid_time,
        "forecast_hour": reference.forecast_hour,
        "members": list(decoded),
        "short_name": short_name,
        "type_of_level": type_of_level,
        "level": level,
    }

def calculate_gefs_ensemble_statistics(
    grib_paths: Iterable[str | Path], *, short_name: str, type_of_level: str, level: float,
    threshold: float | None = None, minimum_members: int = 2,
) -> tuple[dict, dict]:
    """Decode, validate and calculate statistics for one comparable GEFS field."""
    from ecmwf_collector.ensemble_statistics import calculate_ensemble_statistics

    member_fields, field_metadata = decode_gefs_ensemble_fields(
        grib_paths, short_name=short_name, type_of_level=type_of_level, level=level,
        minimum_members=minimum_members,
    )
    statistics = calculate_ensemble_statistics(
        member_fields, threshold=threshold, minimum_members=minimum_members,
    )
    return statistics, field_metadata