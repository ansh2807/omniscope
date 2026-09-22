@echo off
setlocal EnableDelayedExpansion
title OMNISCOPE
cd /d "%~dp0"

echo.
echo   ============================================================
echo     OMNISCOPE — Marketing Intelligence OS
echo   ============================================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo   First run detected. This installs everything the engine needs:
  echo     - a private Python environment
  echo     - the engine's libraries
  echo     - a headless browser, so no API key is needed for
  echo       Instagram and YouTube data
  echo.
  echo   It downloads roughly 200 MB and takes 2-4 minutes ONCE.
  echo   Every run after this one starts in about 5 seconds.
  echo.
)

REM ---------- 1. locate Python -------------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo   [X] Python was not found on this computer.
  echo.
  echo       Install Python 3.10 or newer from https://www.python.org/downloads/
  echo       and tick "Add python.exe to PATH" during setup, then run this again.
  echo.
  pause
  exit /b 1
)
for /f "tokens=2" %%v in ('%PY% --version 2^>^&1') do set "PYVER=%%v"
echo   [1/5] Python %PYVER% found.

REM ---------- 2. virtual environment --------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo   [2/5] Creating the private environment...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo   [X] Could not create the virtual environment.
    pause
    exit /b 1
  )
) else (
  echo   [2/5] Environment ready.
)
set "VPY=.venv\Scripts\python.exe"

REM ---------- 3. dependencies ---------------------------------------------
if not exist ".venv\.installed" (
  echo   [3/5] Installing libraries ^(about 60 seconds^)...
  "%VPY%" -m pip install --upgrade pip --quiet
  "%VPY%" -m pip install -r requirements-dev.txt --quiet
  if errorlevel 1 (
    echo   [X] Library installation failed. Scroll up for the reason.
    pause
    exit /b 1
  )
  echo ok> ".venv\.installed"
) else (
  echo   [3/5] Libraries ready.
)

REM ---------- 4. browser tier ----------------------------------------------
REM This is what removes the need for any API key on Instagram and YouTube.
if "%CI_SKIP_BROWSER%"=="1" goto :afterbrowser
if not exist ".venv\.browser" (
  echo   [4/5] Installing the browser engine ^(about 150 MB, one time^)...
  echo         This is what lets the engine read Instagram and YouTube
  echo         with no API key. Please wait.
  "%VPY%" -m playwright install chromium
  if errorlevel 1 (
    echo.
    echo   [!] The browser download did not complete.
    echo       The engine will still run, but Instagram and YouTube data
    echo       will be limited until this succeeds. You can retry any time
    echo       by running ENABLE-BROWSER.bat
    echo.
  ) else (
    echo ok> ".venv\.browser"
    echo         Browser engine installed.
  )
) else (
  echo   [4/5] Browser engine ready.
)
:afterbrowser

REM ---------- 5. config + key ----------------------------------------------
for /f "delims=" %%k in ('"%VPY%" tools\bootstrap.py') do set "APIKEY=%%k"
if not defined APIKEY (
  echo   [X] Setup failed. Scroll up for the reason.
  pause
  exit /b 1
)
echo   [5/5] Configuration ready.

REM ---------- pick a free port ---------------------------------------------
set "PORT=8000"
for %%p in (8000 8001 8002 8003 8010) do (
  netstat -ano | findstr /r /c:":%%p .*LISTENING" >nul 2>&1
  if errorlevel 1 (
    set "PORT=%%p"
    goto :gotport
  )
)
:gotport

echo.
echo   ------------------------------------------------------------
echo     Ready. Opening  http://localhost:%PORT%
echo.
echo     Paste a creator, website, company or keyword. Creators get
echo     the diligence pack; websites get web intelligence.
echo.
echo     Each report is deleted after 5 minutes. Download HTML,
echo     JSON or Word before then.
echo.
echo     Optional API keys can be added in Settings inside the app.
echo.
echo     Leave this window open. Press Ctrl+C here to stop.
echo   ------------------------------------------------------------
echo.

start "" cmd /c "timeout /t 4 /nobreak >nul && start "" http://localhost:%PORT%/?key=%APIKEY%"
"%VPY%" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%

echo.
echo   Server stopped.
pause
