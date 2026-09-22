@echo off
setlocal
title Creator Intelligence - Self Test
cd /d "%~dp0"

echo.
echo   Running the engine self-test. No internet connection is used.
echo.

if not exist ".venv\Scripts\python.exe" call "%~dp0START-SETUP-ONLY.bat"
set "VPY=.venv\Scripts\python.exe"

"%VPY%" -m pytest tests\ -q
if errorlevel 1 (
  echo.
  echo   [X] Some tests failed. Send the output above to your developer.
) else (
  echo.
  echo   [OK] Everything passed. The engine is working correctly.
)
echo.
pause
