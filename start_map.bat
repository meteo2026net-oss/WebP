@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" serve_map.py
) else (
  where conda >nul 2>nul
  if not errorlevel 1 (
    conda run -n ecmwf-webp python serve_map.py
  ) else (
    py -3.12 serve_map.py
  )
)
pause
