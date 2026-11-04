@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%CD%\src
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" main.py
) else (
  where conda >nul 2>nul
  if not errorlevel 1 (
    conda run -n ecmwf-webp python main.py
  ) else (
    py -3.12 main.py
  )
)
pause
