"""Provenance gate for GEFS members before GRIB decoding and ensemble math.

This module validates downloader sidecars only. It does not decode GRIB or prove
that the grid coordinates inside the files match; those checks remain mandatory
in the GRIB decoding layer.
"""
from __future__ import annotations
import json
import re
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
        try:
            forecast_hour = int(metadata["forecast_hour"])
        except (TypeError, ValueError) as exc:
            raise GefsMemberMetadataError(f"{member} has invalid forecast_hour") from exc
        current = (metadata["source"], metadata["model"], metadata["run"], metadata["valid_time"],
                   forecast_hour, metadata["resolution"], tuple(sorted(map(str, variables))),
                   tuple(sorted(map(str, levels))))
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
        if member in metadata_by_member:
            raise GefsMemberMetadataError(f"duplicate GEFS member supplied: {member}")
        metadata_by_member[member] = metadata
    return validate_gefs_member_metadata(metadata_by_member, minimum_members=minimum_members)