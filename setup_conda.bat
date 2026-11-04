@echo off
setlocal
cd /d "%~dp0"
where conda >nul 2>nul
if errorlevel 1 (
  echo Conda was not found. Install Miniforge first, then reopen this terminal.
  pause
  exit /b 1
)
conda env list | findstr /I "ecmwf-webp" >nul
if errorlevel 1 (
  echo Creating the ecmwf-webp environment...
  conda env create -f environment.yml
) else (
  echo Updating the ecmwf-webp environment...
  conda env update -n ecmwf-webp -f environment.yml --prune
)
if errorlevel 1 (
  echo Environment setup failed. Review the conda error above.
  pause
  exit /b 1
)
echo.
echo Running ecCodes and cfgrib self-checks...
conda run -n ecmwf-webp python -m eccodes selfcheck
conda run -n ecmwf-webp python -m cfgrib selfcheck
echo.
echo Environment ready. Run run_collector_conda.bat to start the application.
pause
