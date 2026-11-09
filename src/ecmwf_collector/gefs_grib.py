"""Provenance gate for GEFS members before GRIB decoding and ensemble math.

This module validates downloader sidecars only. It does not decode GRIB or prove
that the grid coordinates inside the files match; those checks remain mandatory
in the GRIB decoding layer.
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

class GefsMemberMetadataError(ValueError):
    """Raised when GEFS member files cannot safely be grouped."""

_MEMBER_RE = re.compile(r"(?:c00|p(?:0[1-9]|[12][0-9]|30))")

def _read_sidecar(grib_path: Path) -> dict:
    sidecar = grib_path.with_name(grib_path.stem + ".source.json")
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GefsMemberMetadataError(f"metadata sidecar is missing for {grib_path.name}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GefsMemberMetadataError(f"cannot read metadata sidecar for {grib_path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise GefsMemberMetadataError(f"metadata sidecar is not an object: {sidecar.name}")
    return payload

def validate_gefs_member_metadata(metadata_by_member: dict[str, dict], *, minimum_members: int = 2) -> dict[str, dict]:
    """Validate identical forecast identity across members; grids/units need later checks."""
    if minimum_members < 2:
        raise GefsMemberMetadataError("minimum_members must be at least 2")
    if len(metadata_by_member) < minimum_members:
        raise GefsMemberMetadataError(f"need at least {minimum_members} GEFS members; received {len(metadata_by_member)}")
    signature = None
    validated = {}
    for member, metadata in metadata_by_member.items():
        if not _MEMBER_RE.fullmatch(str(member)):
            raise GefsMemberMetadataError(f"invalid GEFS member identifier: {member}")
        if not isinstance(metadata, dict):
            raise GefsMemberMetadataError(f"metadata for {member} must be an object")
        if str(metadata.get("member") or "") != str(member):
            raise GefsMemberMetadataError(
                f"metadata member identifier does not match mapping key {member}"
            )
        if metadata.get("model") != "GEFS":
            raise GefsMemberMetadataError(f"{member} is not labelled as GEFS")
        if metadata.get("source") != "NOAA/NCEP NOMADS":
            raise GefsMemberMetadataError(f"{member} has an unexpected data source")
        variables, levels = metadata.get("variables"), metadata.get("levels")
        if not isinstance(variables, list) or not variables:
            raise GefsMemberMetadataError(f"{member} has no variable list")
        if not isinstance(levels, list) or not levels:
            raise GefsMemberMetadataError(f"{member} has no level list")
        required = (metadata.get("run"), metadata.get("valid_time"), metadata.get("forecast_hour"), metadata.get("resolution"))
        if any(value is None or value == "" for value in required):
            raise GefsMemberMetadataError(f"{member} is missing forecast identity metadata")
        raw_forecast_hour = metadata["forecast_hour"]
        if isinstance(raw_forecast_hour, bool):
            raise GefsMemberMetadataError(f"{member} has invalid forecast_hour")
        try:
            numeric_forecast_hour = float(raw_forecast_hour)
        except (TypeError, ValueError) as exc:
            raise GefsMemberMetadataError(f"{member} has invalid forecast_hour") from exc
        if (not numeric_forecast_hour.is_integer()) or numeric_forecast_hour < 0:
            raise GefsMemberMetadataError(
                f"{member} forecast_hour must be a non-negative whole number"
            )
        forecast_hour = int(numeric_forecast_hour)
        try:
            run_text = str(metadata["run"])
            valid_text = str(metadata["valid_time"])
            run_dt = datetime.fromisoformat(run_text.replace("Z", "+00:00"))
            valid_dt = datetime.fromisoformat(valid_text.replace("Z", "+00:00"))
            if run_dt.tzinfo is None or valid_dt.tzinfo is None:
                raise ValueError("timestamps must include a UTC offset")
            run_utc = run_dt.utcoffset()
            valid_utc = valid_dt.utcoffset()
            if run_utc is None or valid_utc is None:
                raise ValueError("timestamps must include a UTC offset")
            if valid_dt.astimezone(run_dt.tzinfo) != run_dt + timedelta(hours=forecast_hour):
                raise GefsMemberMetadataError(
                    f"{member} valid_time does not match run plus forecast_hour"
                )
        except GefsMemberMetadataError:
            raise
        except (TypeError, ValueError) as exc:
            raise GefsMemberMetadataError(
                f"{member} has invalid run/valid_time metadata: {exc}"
            ) from exc
        current = (metadata["source"], metadata["model"], run_dt.astimezone(timezone.utc).isoformat(),
                   valid_dt.astimezone(timezone.utc).isoformat(), forecast_hour, metadata["resolution"],
                   tuple(sorted(map(str, variables))), tuple(sorted(map(str, levels))))
        if signature is None:
            signature = current
        elif current != signature:
            labels = ("source", "model", "run", "valid_time", "forecast_hour", "resolution", "variables", "levels")
            mismatch = [label for label, left, right in zip(labels, signature, current) if left != right]
            raise GefsMemberMetadataError(f"{member} is not comparable with the other members; mismatched: {chr(44).join(mismatch)}")
        validated[member] = metadata
    return validated

def load_gefs_member_metadata(grib_paths: Iterable[str | Path], *, minimum_members: int = 2) -> dict[str, dict]:
    """Load sidecars for GRIB paths and validate their shared forecast identity."""
    metadata_by_member = {}
    for raw_path in grib_paths:
        path = Path(raw_path)
        if not path.is_file():
            raise GefsMemberMetadataError(f"GRIB member file does not exist: {path}")
        metadata = _read_sidecar(path)
        member = str(metadata.get("member") or "")
        if metadata.get("file_name") != path.name:
            raise GefsMemberMetadataError(f"sidecar filename does not match GRIB file: {path.name}")
        try:
            expected_size = int(metadata["size_bytes"])
            expected_digest = str(metadata["sha256"]).lower()
        except (KeyError, TypeError, ValueError) as exc:
            raise GefsMemberMetadataError(
                f"sidecar is missing valid size/checksum metadata for {path.name}"
            ) from exc
        if expected_size != path.stat().st_size:
            raise GefsMemberMetadataError(f"GRIB file size does not match sidecar: {path.name}")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise GefsMemberMetadataError(f"sidecar SHA-256 is invalid: {path.name}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_digest:
            raise GefsMemberMetadataError(f"GRIB file SHA-256 does not match sidecar: {path.name}")
        if member in metadata_by_member:
            raise GefsMemberMetadataError(f"duplicate GEFS member supplied: {member}")
        metadata_by_member[member] = metadata
    return validate_gefs_member_metadata(metadata_by_member, minimum_members=minimum_members)