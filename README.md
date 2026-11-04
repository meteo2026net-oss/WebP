# ECMWF WebP Weather Data Platform

مشروع مفتوح المصدر لتنزيل بيانات ECMWF WMO Support، وفحص ملفات GRIB/BUFR، وتحويل الحقول الجوية المتوافقة إلى طبقات خرائط.

**الوثائق العربية:** [README_AR.md](README_AR.md) — **مسار GRIB إلى الخريطة:** [MAP_PIPELINE.md](docs/MAP_PIPELINE.md)

## Project layout
- `src/ecmwf_collector/`: desktop collector package and GUI.
- `src/ecmwf_collector/tools/`: GRIB inspection, conversion, batch processing, and WebP encoding/decoding.
- `map_viewer/`: interactive Leaflet map interface.
- `tests/`: unit tests and fake FTP server.
- `docs/`: technical documentation.
- `config/settings.example.json`: safe local configuration template.
- `archive/`: original uploaded source archive.

## Recommended Windows install (Miniforge / conda-forge)

The GRIB decoder has native binary dependencies. ECMWF documents conda-forge as the easiest installation route for ecCodes and cfgrib with their binary dependencies. Windows support is community-supported rather than ECMWF's primary operational platform.

1. Install Miniforge from [the official project](https://github.com/conda-forge/miniforge).
2. Open a new terminal in this repository and run `setup_conda.bat`.
3. Run `run_collector_conda.bat`.

The setup script creates or updates the `ecmwf-webp` environment and runs the ecCodes and cfgrib self-checks.

### Alternative pip install
```powershell
py -3.12 -m venv .venv
.venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item config/settings.example.json config/settings.json
python main.py
```

Never commit local settings, credentials, database files, logs, or downloaded data. Prefer FTPS/TLS; plain FTP is unencrypted and disabled by default.

## Windows shortcuts

- `run_collector.bat`: start the desktop downloader.
- `process_downloads.bat`: scan downloaded GRIB files and build map layers.
- `start_map.bat`: start the restricted localhost map viewer.

## End-to-end workflow

1. Use the desktop collector to connect to the ECMWF WMO Support server and download GRIB files into `downloads/`.
2. Inspect a file and identify its actual fields:
```powershell
$env:PYTHONPATH = "src"
python -m ecmwf_collector.tools.inspect_grib path/to/file.grib2 --output output/inventory.json
``
3. Convert every compatible regular latitude/longitude scalar field, including its separate forecast-time and vertical-level slices:
```powershell
python -m ecmwf_collector.tools.grib_to_map path/to/file.grib2 --output-dir output/map_data
``
4. Or process the downloaded tree in one batch:
```powershell
python -m ecmwf_collector.tools.process_downloads --downloads downloads --output-dir output/map_data
``
5. For U/V wind components, create both the scientific RGB WebP texture and a wind-speed display overlay:
```powershell
python -m ecmwf_collector.tools.wind_grib_to_webp path/to/wind.grib2 --output output/wind.webp
``
6. Start a local web server from the repository root and open the map:
```powershell
python serve_map.py
``
Open `http://127.0.0.1:8765/map_viewer/`. The map reads `output/map_data/manifest.json`. Click the map to query the nearest original GRIB grid cell; this requires the matching `.npz` data file.

## Tests
```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -t . -v
```

Tests use synthetic arrays and fake FTP sessions; they do not prove compatibility with the live ECMWF service or every GRIB grid projection.

## Current scientific and geographic limitations
The initial map renderer and nearest-point sampler support regular 1-D latitude/longitude grids only. Multi-step and multi-level fields are split into separately selectable layers when cfgrib exposes their dimensions. Click a map location to retrieve the nearest stored value, units, and valid time (nearest-neighbour only; no bilinear interpolation yet). Rotated-pole, Lambert, polar stereographic, curvilinear, and other projected grids need reprojection before map display. The converter deliberately rejects unsupported grids rather than placing them incorrectly.

The RGB WebP wind texture uses 8-bit quantization. Lossless WebP preserves encoded channel bytes, not original floating-point precision. PNG overlays are display products, not scientific source data. Preserve original GRIB files for scientific calculations.
