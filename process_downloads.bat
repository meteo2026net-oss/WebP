@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%CD%\src
py -3.12 -m ecmwf_collector.tools.process_downloads --downloads downloads --output-dir output\map_data
echo.
echo Processing finished. Start start_map.bat to view the map.
pause
