# Architecture

## Desktop collector
The `ecmwf_collector` package contains connection handling, remote directory listing, download planning, resumable transfer, file inspection, state persistence, secret storage, and the PySide6 interface.

## GRIB processing tools
The `tools` package contains GRIB metadata inventory, wind U/V WebP encoding, WebP decoding, and an optional Tkinter GRIB explorer.

## Local runtime data
The application creates `downloads/`, `processed/`, `output/`, `logs/`, `state/`, and `config/settings.json` locally. These are runtime data and must not be committed.

## Trust boundaries
Credentials and operational data stay on the user's machine. The repository should contain source code, documentation, safe example configuration, and synthetic tests only.
