# ECMWF WebP Weather Data Platform

مشروع مفتوح المصدر لتنزيل بيانات ECMWF WMO Support، وفحص ملفات GRIB/BUFR، وتجهيز الحقول الجوية للتحويل إلى صور وطبقات مكانية قابلة للعرض على الخرائط.

**الوثائق العربية:** [README_AR.md](README_AR.md)

## Project layout
- `src/ecmwf_collector/`: desktop collector package and GUI.
- `src/ecmwf_collector/tools/`: GRIB inspection, WebP encoding/decoding, and GRIB explorer.
- `tests/`: unit tests and fake FTP server.
- `docs/`: technical documentation.
- `config/settings.example.json`: safe local configuration template.
- `archive/`: original uploaded source archive.

Runtime data (`downloads/`, `processed/`, `output/`, `logs/`, and `state/`) is created locally and excluded from Git.

## Install (Windows)
```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item config/settings.example.json config/settings.json
python main.py
```

Never commit local settings, credentials, database files, logs, or downloaded data. Prefer FTPS/TLS; plain FTP is unencrypted and disabled by default.

## GRIB tools
```powershell
$env:PYTHONPATH = "src"
python -m ecmwf_collector.tools.inspect_grib path/to/input.grib2 --output output/grib_inventory.json
python -m ecmwf_collector.tools.wind_grib_to_webp path/to/input.grib2 --output output/wind.webp
python -m ecmwf_collector.tools.webp_to_npz output/wind.webp --output output/wind_decoded.npz
```

## Tests
```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -t . -v
```

Tests use synthetic data and fake FTP sessions; they do not prove compatibility with the live ECMWF service or all GRIB grid projections.

## Scientific limitation
The current wind encoder uses 8-bit quantization and supports only one-dimensional latitude/longitude coordinates. Lossless WebP preserves encoded channel bytes, not original floating-point precision. Keep original GRIB files for scientific calculations and verify projection, longitude convention, orientation, and georeferencing before map display.
