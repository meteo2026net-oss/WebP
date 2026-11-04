@echo off
setlocal
cd /d "%~dp0"
where conda >nul 2>nul
if errorlevel 1 (
  echo Conda was not found. Install Miniforge first, then reopen this terminal.
  pause
  exit /b 1
)
echo Creating or updating the ecmwf-webp environment...
conda env update -n ecmwf-webp -f environment.yml --prune
if errorlevel 1 (
  echo Environment setup failed. Review the conda error above.
  pause
  exit /b 1
)
echo.
echo Environment ready. Run run_collector_conda.bat to start the application.
pause
