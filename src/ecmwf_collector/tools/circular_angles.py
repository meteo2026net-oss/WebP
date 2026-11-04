"""Circular statistics for meteorological direction angles."""
from __future__ import annotations

import numpy as np


def circular_mean_degrees(directions, weights=None, *, axis=None, tolerance=1e-12):
    """Return weighted circular mean in [0, 360); undefined means return NaN."""
    angles = np.asarray(directions, dtype=np.float64)
    radians = np.deg2rad(angles)
    if weights is None:
        weight = np.ones_like(angles, dtype=np.float64)
    else:
        weight = np.asarray(weights, dtype=np.float64)
        try:
            weight = np.broadcast_to(weight, angles.shape)
        except ValueError as exc:
            raise ValueError("Weights must be broadcastable to directions.") from exc
        if np.any(np.isfinite(weight) & (weight < 0)):
            raise ValueError("Circular weights must be non-negative.")
    valid = np.isfinite(angles) & np.isfinite(weight) & (weight > 0)
    sin_sum = np.sum(np.where(valid, np.sin(radians) * weight, 0.0), axis=axis)
    cos_sum = np.sum(np.where(valid, np.cos(radians) * weight, 0.0), axis=axis)
    total = np.sum(np.where(valid, weight, 0.0), axis=axis)
    magnitude = np.hypot(sin_sum, cos_sum)
    result = (np.rad2deg(np.arctan2(sin_sum, cos_sum)) + 360.0) % 360.0
    return np.where((total > 0) & (magnitude > tolerance * np.maximum(total, 1.0)), result, np.nan)


def interpolate_direction_degrees(directions, weights, *, axis=-1):
    """Interpolate direction samples with weighted sine/cosine components."""
    return circular_mean_degrees(directions, weights, axis=axis)
