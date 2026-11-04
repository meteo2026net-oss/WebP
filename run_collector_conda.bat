@echo off
setlocal
cd /d "%~dp0"
where conda >nul 2>nul
if errorlevel 1 (
  echo Conda was not found. Install Miniforge and run setup_conda.bat first.
  pause
  exit /b 1
)
call conda run -n ecmwf-webp python main.py
pause
