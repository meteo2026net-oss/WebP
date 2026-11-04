"""Explicit, conservative unit conversions for common meteorological fields."""
from __future__ import annotations

import numpy as np

# Each entry maps a normalized alias to (dimension, scale_to_base, offset_to_base, label).
# Base units: Pa, K, m s-1, and m respectively.
_UNITS = {
    "pa": ("pressure", 1.0, 0.0, "Pa"),
    "pascal": ("pressure", 1.0, 0.0, "Pa"),
    "pascals": ("pressure", 1.0, 0.0, "Pa"),
    "hpa": ("pressure", 100.0, 0.0, "hPa"),
    "hectopascal": ("pressure", 100.0, 0.0, "hPa"),
    "hectopascals": ("pressure", 100.0, 0.0, "hPa"),
    "mbar": ("pressure", 100.0, 0.0, "hPa"),
    "millibar": ("pressure", 100.0, 0.0, "hPa"),
    "millibars": ("pressure", 100.0, 0.0, "hPa"),
    "kpa": ("pressure", 1000.0, 0.0, "kPa"),
    "k": ("temperature", 1.0, 0.0, "K"),
    "kelvin": ("temperature", 1.0, 0.0, "K"),
    "degc": ("temperature", 1.0, 273.15, "°C"),
    "c": ("temperature", 1.0, 273.15, "°C"),
    "celsius": ("temperature", 1.0, 273.15, "°C"),
    "°c": ("temperature", 1.0, 273.15, "°C"),
    "deg c": ("temperature", 1.0, 273.15, "°C"),
    "degree celsius": ("temperature", 1.0, 273.15, "°C"),
    "degrees celsius": ("temperature", 1.0, 273.15, "°C"),
    "ms-1": ("speed", 1.0, 0.0, "m s-1"),
    "m/s": ("speed", 1.0, 0.0, "m s-1"),
    "m s-1": ("speed", 1.0, 0.0, "m s-1"),
    "m s**-1": ("speed", 1.0, 0.0, "m s-1"),
    "m s^-1": ("speed", 1.0, 0.0, "m s-1"),
    "m s**(-1)": ("speed", 1.0, 0.0, "m s-1"),
    "kmh-1": ("speed", 1.0 / 3.6, 0.0, "km h-1"),
    "km/h": ("speed", 1.0 / 3.6, 0.0, "km h-1"),
    "kph": ("speed", 1.0 / 3.6, 0.0, "km h-1"),
    "km h-1": ("speed", 1.0 / 3.6, 0.0, "km h-1"),
    "km h**-1": ("speed", 1.0 / 3.6, 0.0, "km h-1"),
    "km h^-1": ("speed", 1.0 / 3.6, 0.0, "km h-1"),
    "kn": ("speed", 0.5144444444444445, 0.0, "kn"),
    "knot": ("speed", 0.5144444444444445, 0.0, "kn"),
    "knots": ("speed", 0.5144444444444445, 0.0, "kn"),
    "m": ("length", 1.0, 0.0, "m"),
    "meter": ("length", 1.0, 0.0, "m"),
    "meters": ("length", 1.0, 0.0, "m"),
    "metre": ("length", 1.0, 0.0, "m"),
    "metres": ("length", 1.0, 0.0, "m"),
    "mm": ("length", 0.001, 0.0, "mm"),
    "millimeter": ("length", 0.001, 0.0, "mm"),
    "millimeters": ("length", 0.001, 0.0, "mm"),
    "millimetre": ("length", 0.001, 0.0, "mm"),
    "millimetres": ("length", 0.001, 0.0, "mm"),
}


def _key(unit: str) -> str:
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError("A non-empty source and target unit are required.")
    normalized = unit.strip().lower().replace("°", "deg")
    normalized = normalized.replace("−", "-").replace("·", " ")
    return " ".join(normalized.split())


def unit_info(unit: str) -> tuple[str, float, float, str]:
    """Return dimension, scale, offset, and canonical display label."""
    key = _key(unit)
    try:
        return _UNITS[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported meteorological unit: {unit!r}") from exc


def canonical_unit(unit: str) -> str:
    """Return a canonical label for a supported unit alias."""
    return unit_info(unit)[3]


def convert_values(values, source_unit: str, target_unit: str):
    """Convert scalars or arrays; unknown units and cross-dimension conversion fail."""
    source = unit_info(source_unit)
    target = unit_info(target_unit)
    if source[0] != target[0]:
        raise ValueError(
            f"Incompatible units: {source_unit!r} ({source[0]}) and "
            f"{target_unit!r} ({target[0]})."
        )
    array = np.asarray(values, dtype=np.float64)
    base = array * source[1] + source[2]
    converted = (base - target[2]) / target[1]
    if converted.ndim == 0:
        return float(converted)
    return converted
