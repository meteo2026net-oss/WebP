"""Numerically safe ensemble statistics for already-decoded, aligned fields.

This module deliberately accepts arrays rather than reading GRIB files. Callers must
decode fields and align their grid, valid time, units and vertical level first.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np


class EnsembleStatisticsError(ValueError):
    """Raised when ensemble members cannot be compared safely."""


def calculate_ensemble_statistics(
    member_fields: Mapping[str, Any],
    *,
    threshold: float | None = None,
    minimum_members: int = 2,
) -> dict[str, Any]:
    """Compute per-gridpoint mean, population spread and optional exceedance chance.

    Non-finite cells are treated as missing independently at each grid point.
    Probability denominator is the number of valid members at that grid point.
    """
    if minimum_members < 2:
        raise EnsembleStatisticsError("minimum_members must be at least 2")
    if len(member_fields) < minimum_members:
        raise EnsembleStatisticsError(
            f"need at least {minimum_members} members; received {len(member_fields)}"
        )
    names = list(member_fields)
    if len(set(names)) != len(names) or any(not str(name).strip() for name in names):
        raise EnsembleStatisticsError("member names must be non-empty and unique")

    arrays = []
    expected_shape = None
    for name in names:
        try:
            values = np.asarray(member_fields[name], dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise EnsembleStatisticsError(f"member {name} is not a numeric field") from exc
        if values.ndim < 1:
            raise EnsembleStatisticsError(f"member {name} must contain a grid")
        if expected_shape is None:
            expected_shape = values.shape
        elif values.shape != expected_shape:
            raise EnsembleStatisticsError("all member grids must have identical shapes")
        arrays.append(values)

    stack = np.stack(arrays, axis=0)
    valid = np.isfinite(stack)
    count = valid.sum(axis=0)
    safe = np.where(valid, stack, 0.0)
    total = safe.sum(axis=0)
    mean = np.full(expected_shape, np.nan, dtype=np.float64)
    np.divide(total, count, out=mean, where=count > 0)

    centered = np.where(valid, stack - mean, 0.0)
    variance = np.full(expected_shape, np.nan, dtype=np.float64)
    np.divide((centered * centered).sum(axis=0), count, out=variance, where=count > 0)
    spread = np.sqrt(variance)
    insufficient = count < minimum_members
    mean[insufficient] = np.nan
    spread[insufficient] = np.nan

    result = {
        "member_count": count,
        "mean": mean,
        "spread": spread,
        "members_used": names,
        "minimum_members": minimum_members,
        "statistics": ["mean", "population_standard_deviation"],
    }
    if threshold is not None:
        exceed = (stack > float(threshold)) & valid
        probability = np.full(expected_shape, np.nan, dtype=np.float64)
        np.divide(exceed.sum(axis=0) * 100.0, count, out=probability, where=count > 0)
        probability[insufficient] = np.nan
        result["probability_exceeding_threshold_percent"] = probability
        result["threshold"] = float(threshold)
        result["statistics"].append("probability_exceeding_threshold_percent")
    return result
