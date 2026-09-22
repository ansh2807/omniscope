@echo off
setlocal
title Creator Intelligence - Calibration
cd /d "%~dp0"

echo.
echo   ============================================================
echo     CREATOR INTELLIGENCE - CALIBRATION SUITE
echo   ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo   [X] The project environment is not installed yet.
  echo       Run START.bat once, then run CALIBRATE.bat again.
  echo.
  pause
  exit /b 1
)

echo   Running the diverse creator and adversarial accuracy corpus...
echo.
".venv\Scripts\python.exe" "tools\calibrate_engine.py"
set "RESULT=%ERRORLEVEL%"

echo.
if "%RESULT%"=="0" (
  echo   [OK] Calibration passed. No accuracy-contract failures found.
) else (
  echo   [X] Calibration found one or more failures. Review the issues above.
)
echo.
pause
exit /b %RESULT%
