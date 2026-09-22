#!/usr/bin/env bash
# One click, everything. macOS and Linux.   chmod +x start.sh && ./start.sh
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "  ============================================================"
echo "    CREATOR INTELLIGENCE ENGINE"
echo "  ============================================================"
echo
if [ ! -x ".venv/bin/python" ]; then
  echo "  First run detected. This installs everything the engine needs:"
  echo "    - a private Python environment"
  echo "    - the engine's libraries"
  echo "    - a headless browser, so no API key is needed for"
  echo "      Instagram and YouTube data"
  echo
  echo "  It downloads roughly 200 MB and takes 2-4 minutes ONCE."
  echo "  Every run after this one starts in about 5 seconds."
  echo
fi

PY=""
for c in python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "  [X] Python 3.10+ not found. Install it and run this again."
  exit 1
fi
echo "  [1/5] $($PY --version) found."

if [ ! -x ".venv/bin/python" ]; then
  echo "  [2/5] Creating the private environment..."
  "$PY" -m venv .venv
else
  echo "  [2/5] Environment ready."
fi
VPY=".venv/bin/python"

if [ ! -f ".venv/.installed" ]; then
  echo "  [3/5] Installing libraries (about 60 seconds)..."
  "$VPY" -m pip install --upgrade pip --quiet
  "$VPY" -m pip install -r requirements-dev.txt --quiet
  touch .venv/.installed
else
  echo "  [3/5] Libraries ready."
fi

if [ "${CI_SKIP_BROWSER:-0}" != "1" ]; then
  if [ ! -f ".venv/.browser" ]; then
    echo "  [4/5] Installing the browser engine (about 150 MB, one time)..."
    echo "        This is what lets the engine read Instagram and YouTube"
    echo "        with no API key. Please wait."
    if "$VPY" -m playwright install chromium; then
      touch .venv/.browser
      echo "        Browser engine installed."
    else
      echo
      echo "  [!] The browser download did not complete. The engine will still run,"
      echo "      but Instagram and YouTube data will be limited. Retry any time"
      echo "      with ./enable-browser.sh"
      echo
    fi
  else
    echo "  [4/5] Browser engine ready."
  fi
fi

APIKEY="$("$VPY" tools/bootstrap.py | tail -n 1)"
echo "  [5/5] Configuration ready."

PORT=8000
for p in 8000 8001 8002 8003 8010; do
  if ! (command -v lsof >/dev/null && lsof -i :"$p" >/dev/null 2>&1); then PORT=$p; break; fi
done

echo
echo "  ------------------------------------------------------------"
echo "    Ready. Opening  http://localhost:$PORT"
echo
echo "    Paste one creator link for a single report, or several"
echo "    (one per line) for a cohort report that compares them."
echo
echo "    Optional API keys can be added in Settings inside the app."
echo
echo "    Leave this window open. Press Ctrl+C here to stop."
echo "  ------------------------------------------------------------"
echo

( sleep 4
  URL="http://localhost:$PORT/?key=$APIKEY"
  if command -v open >/dev/null; then open "$URL"
  elif command -v xdg-open >/dev/null; then xdg-open "$URL"
  fi ) &

exec "$VPY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
