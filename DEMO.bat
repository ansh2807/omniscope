@echo off
setlocal
title Creator Intelligence - Sample Reports
cd /d "%~dp0"

echo.
echo   Generating sample reports from the bundled fixtures.
echo   No internet connection is used.
echo.

if not exist ".venv\Scripts\python.exe" (
  echo   Setting up first ^(one time^)...
  call "%~dp0START-SETUP-ONLY.bat"
  if errorlevel 1 exit /b 1
)
set "VPY=.venv\Scripts\python.exe"

"%VPY%" scripts_demo.py
if errorlevel 1 (
  echo   [X] Sample generation failed.
  pause
  exit /b 1
)

echo.
echo   Opening the cohort report...
start "" "data\samples\cohort.html"
timeout /t 1 /nobreak >nul
start "" "data\samples\sunil_panda.html"
echo.
echo   All samples are in:  %CD%\data\samples
echo.
pause
