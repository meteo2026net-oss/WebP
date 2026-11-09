"""Validated deterministic comparison of gridded forecast fields.

The first implementation intentionally compares identical grids only. It never
silently regrids data: callers must use a separately validated regridding step
and record its method before invoking this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

import numpy as np


class ModelComparisonError(ValueError):
    """Raised when forecast fields are not scientifically comparable."""


@dataclass(frozen=True)
class ForecastField:
    values: Any
    model: str
    variable: str
    level_type: str
    level_value: float
    level_unit: str
    valid_time: str
    units: str
    grid_id: str


# Conversion is deliberately explicit and limited to unambiguous common units.
# Each entry maps a normalized source unit to (dimension, scale, offset), where
# canonical_value = source_value * scale + offset.
_UNIT_MAP = {
    "k": ("temperature", 1.0, -273.15),
    "kelvin": ("temperature", 1.0, -273.15),
    "c": ("temperature", 1.0, 0.0),
    "°c": ("temperature", 1.0, 0.0),
    "degc": ("temperature", 1.0, 0.0),
    "pa": ("pressure", 1.0, 0.0),
    "hpa": ("pressure", 100.0, 0.0),
    "m/s": ("speed", 1.0, 0.0),
    "m s-1": ("speed", 1.0, 0.0),
    "km/h": ("speed", 1.0 / 3.6, 0.0),
    "mm": ("precipitation", 1.0, 0.0),
    "kg m-2": ("precipitation", 1.0, 0.0),
}


def _utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ModelComparisonError("valid_time must be a non-empty ISO-8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ModelComparisonError(f"invalid valid_time: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _unit_transform(unit: str) -> tuple[str, float, float]:
    key = " ".join(str(unit).strip().lower().split())
    try:
        return _UNIT_MAP[key]
    except KeyError as exc:
        raise ModelComparisonError(
            f"unsupported or ambiguous unit {unit!r}; register an explicit conversion first"
        ) from exc


def _values(field: ForecastField, name: str) -> np.ndarray:
    try:
        array = np.asarray(field.values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ModelComparisonError(f"{name} values are not numeric") from exc
    if array.ndim < 1:
        raise ModelComparisonError(f"{name} must contain a gridded array")
    return array


def _validate_pair(reference: ForecastField, candidate: ForecastField) -> tuple[np.ndarray, np.ndarray, str]:
    for label, field in (("reference", reference), ("candidate", candidate)):
        required = (field.model, field.variable, field.level_type, field.level_unit,
                    field.valid_time, field.units, field.grid_id)
        if any(not str(value).strip() for value in required):
            raise ModelComparisonError(f"{label} metadata contains an empty required value")
    if reference.variable != candidate.variable:
        raise ModelComparisonError("variable mismatch")
    if reference.level_type != candidate.level_type:
        raise ModelComparisonError("vertical level type mismatch")
    if not np.isclose(float(reference.level_value), float(candidate.level_value), rtol=0, atol=1e-9):
        raise ModelComparisonError("vertical level value mismatch")
    if reference.level_unit.strip().lower() != candidate.level_unit.strip().lower():
        raise ModelComparisonError("vertical level unit mismatch")
    if _utc(reference.valid_time) != _utc(candidate.valid_time):
        raise ModelComparisonError("valid_time mismatch")
    if reference.grid_id != candidate.grid_id:
        raise ModelComparisonError(
            "grid mismatch; regrid explicitly and record the method before comparison"
        )
    ref_dim, _, _ = _unit_transform(reference.units)
    cand_dim, scale, offset = _unit_transform(candidate.units)
    if ref_dim != cand_dim:
        raise ModelComparisonError("physical quantity/unit dimension mismatch")
    ref = _values(reference, "reference")
    cand = _values(candidate, "candidate")
    if ref.shape != cand.shape:
        raise ModelComparisonError("array shape mismatch despite matching grid identifier")
    # Convert both fields to the canonical base unit for the dimension.
    _, ref_scale, ref_offset = _unit_transform(reference.units)
    ref_canonical = ref * ref_scale + ref_offset
    cand_canonical = cand * scale + offset
    return ref_canonical, cand_canonical, ref_dim


def calculate_pair_metrics(
    reference: ForecastField,
    candidate: ForecastField,
    *,
    precipitation_threshold: float | None = None,
) -> dict[str, Any]:
    """Calculate candidate-minus-reference scores over common finite cells."""
    ref, pred, dimension = _validate_pair(reference, candidate)
    valid = np.isfinite(ref) & np.isfinite(pred)
    count = int(valid.sum())
    if count == 0:
        raise ModelComparisonError("no overlapping finite grid cells")
    obs, fcst = ref[valid], pred[valid]
    error = fcst - obs
    result: dict[str, Any] = {
        "reference_model": reference.model,
        "candidate_model": candidate.model,
        "dimension": dimension,
        "canonical_unit": {
            "temperature": "degC", "pressure": "Pa", "speed": "m/s",
            "precipitation": "mm",
        }[dimension],
        "sample_count": count,
        "bias": float(np.mean(error)),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "correlation": (
            float(np.corrcoef(obs, fcst)[0, 1])
            if count >= 2 and np.std(obs) > 0 and np.std(fcst) > 0 else None
        ),
        "missing_reference": int((~np.isfinite(ref)).sum()),
        "missing_candidate": int((~np.isfinite(pred)).sum()),
        "error_sign": "candidate_minus_reference",
    }
    if precipitation_threshold is not None:
        if dimension != "precipitation":
            raise ModelComparisonError("precipitation_threshold requires precipitation fields")
        threshold = float(precipitation_threshold)
        if not np.isfinite(threshold) or threshold < 0:
            raise ModelComparisonError("precipitation_threshold must be finite and non-negative")
        observed_event = obs >= threshold
        forecast_event = fcst >= threshold
        hits = int(np.sum(observed_event & forecast_event))
        misses = int(np.sum(observed_event & ~forecast_event))
        false_alarms = int(np.sum(~observed_event & forecast_event))
        correct_negatives = int(np.sum(~observed_event & ~forecast_event))
        result["precipitation"] = {
            "threshold": threshold,
            "hits": hits,
            "misses": misses,
            "false_alarms": false_alarms,
            "correct_negatives": correct_negatives,
            "pod": hits / (hits + misses) if hits + misses else None,
            "far": false_alarms / (hits + false_alarms)
                if hits + false_alarms else None,
            "csi": hits / (hits + misses + false_alarms)
                if hits + misses + false_alarms else None,
        }
    return result


def compare_forecast_models(
    fields: Mapping[str, ForecastField],
    *,
    reference_model: str,
    precipitation_threshold: float | None = None,
) -> dict[str, Any]:
    """Compare every supplied model against one explicit reference model."""
    if len(fields) < 2:
        raise ModelComparisonError("at least two forecast models are required")
    if reference_model not in fields:
        raise ModelComparisonError(f"reference model {reference_model!r} was not supplied")
    if any(key != field.model for key, field in fields.items()):
        raise ModelComparisonError("mapping keys must exactly match each field's model name")
    reference = fields[reference_model]
    comparisons = {}
    for name, field in fields.items():
        if name == reference_model:
            continue
        comparisons[name] = calculate_pair_metrics(
            reference, field, precipitation_threshold=precipitation_threshold
        )
    return {
        "reference_model": reference_model,
        "variable": reference.variable,
        "level_type": reference.level_type,
        "level_value": reference.level_value,
        "level_unit": reference.level_unit,
        "valid_time": _utc(reference.valid_time).isoformat().replace("+00:00", "Z"),
        "grid_id": reference.grid_id,
        "comparisons": comparisons,
    }
