"""Portable, source-separated data storage layout for the desktop application."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def data_root(project_root: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Return the shared data root, honoring an explicit override first."""
    env = os.environ if environ is None else environ
    override = str(env.get("ECMWF_WEBP_DATA_ROOT", "")).strip()
    if override:
        return Path(override).expanduser()
    external = Path("E:/WebP_Data")
    if os.name == "nt" and external.is_dir():
        return external
    return Path(project_root) / "data"


def source_output_dir(source: str, project_root: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Return a dedicated download directory for a known data provider."""
    allowed = {
        "WMO", "ECMWF", "NOAA", "DWD", "CPTEC_ETA",
        "UK_Met_Office", "JMA", "Meteo_France", "Copernicus", "EUMETSAT",
    }
    if source not in allowed:
        raise ValueError(f"Unknown data source: {source}")
    return data_root(project_root, environ) / "Sources" / source


def default_wmo_download_root(
    configured: str, project_root: Path, environ: Mapping[str, str] | None = None
) -> Path:
    """Preserve user paths; redirect only the untouched legacy downloads default."""
    path = Path(configured or "downloads").expanduser()
    if path.is_absolute():
        return path
    if path.as_posix().strip("./").lower() == "downloads":
        return source_output_dir("WMO", project_root, environ)
    return Path(project_root) / path


def processing_output_dir(project_root: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Canonical destination for generated map layers and their manifest."""
    return data_root(project_root, environ) / "Processing" / "MapData"
