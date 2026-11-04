@echo off
setlocal
cd /d "%~dp0"
py -3.12 serve_map.py
pause
