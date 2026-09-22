@echo off
setlocal
title Creator Intelligence - Enable Browser Tier
cd /d "%~dp0"

echo.
echo   ============================================================
echo     ENABLE THE BROWSER TIER
echo   ============================================================
echo.
echo   This installs a headless Chromium (about 150 MB) so the engine
echo   can read pages the way a person does - logged out, no API key.
echo.
echo   It is what lets the engine collect:
echo     - Instagram follower counts, bio, highlights, verification
echo     - YouTube "Popular" sort with all-time view counts
echo     - YouTube comment threads
echo.
echo   Without it, those need a free YouTube API key instead.
echo.
pause

if not exist ".venv\Scripts\python.exe" (
  echo   Setting up the environment first...
  call "%~dp0START-SETUP-ONLY.bat"
  if errorlevel 1 exit /b 1
)
set "VPY=.venv\Scripts\python.exe"

echo.
echo   [1/2] Installing the Playwright library...
"%VPY%" -m pip install playwright --quiet
if errorlevel 1 (
  echo   [X] Install failed.
  pause
  exit /b 1
)

echo   [2/2] Downloading Chromium ^(this is the big one^)...
"%VPY%" -m playwright install chromium
if errorlevel 1 (
  echo   [X] Chromium download failed. Check your connection or proxy.
  pause
  exit /b 1
)

echo.
echo   Done. The browser tier is now active.
echo   BROWSER_MODE is set to "auto" in .env, so the engine will use it
echo   automatically whenever the cheaper methods come back empty.
echo.
echo   Set BROWSER_MODE="always" in .env to prefer it from the start.
echo.
pause
