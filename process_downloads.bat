@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%CD%\src
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m ecmwf_collector.tools.process_downloads --downloads downloads --output-dir output\map_data
) else (
  where conda >nul 2>nul
  if not errorlevel 1 (
    conda run -n ecmwf-webp python -m ecmwf_collector.tools.process_downloads --downloads downloads --output-dir output\map_data
  ) else (
    py -3.12 -m ecmwf_collector.tools.process_downloads --downloads downloads --output-dir output\map_data
  )
)
echo.
echo Processing finished. Start start_map.bat to view the map.
pause
