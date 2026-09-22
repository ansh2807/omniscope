@echo off
REM Shared setup used by DEMO.bat and TEST.bat. Not meant to be run directly.
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo   [X] Python not found. Install Python 3.10+ from python.org with "Add to PATH" ticked.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
set "VPY=.venv\Scripts\python.exe"
if not exist ".venv\.installed" (
  "%VPY%" -m pip install --upgrade pip --quiet
  "%VPY%" -m pip install -r requirements-dev.txt --quiet
  if errorlevel 1 ( pause & exit /b 1 )
  echo ok> ".venv\.installed"
)
"%VPY%" tools\bootstrap.py >nul
exit /b 0
