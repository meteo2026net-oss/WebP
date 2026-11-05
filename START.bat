@echo off
setlocal
cd /d "%~dp0"
set "APP_EXE=%~dp0ECMWFWebP.exe"
if exist "%APP_EXE%" (
  start "" "%APP_EXE%"
  exit /b 0
)
set "APP_EXE=%~dp0dist\ECMWFWebP\ECMWFWebP.exe"
if exist "%APP_EXE%" (
  start "" "%APP_EXE%"
  exit /b 0
)
echo.
echo ECMWF WebP - Windows first-time setup
echo ------------------------------------
echo The portable desktop build is not present yet.
echo This launcher will build it from source when Python 3.12 and Git are available.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_windows.ps1"
if errorlevel 1 (
  echo.
  echo Setup failed. Review the error above.
  pause
  exit /b 1
)
if exist "%APP_EXE%" (
  start "" "%APP_EXE%"
  exit /b 0
)
echo Build finished but the expected EXE was not found.
pause
exit /b 1
