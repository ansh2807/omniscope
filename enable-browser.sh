#!/usr/bin/env bash
# Enable the browser tier: read public pages the way a person does, no API key.
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "  Installing the browser tier (~150 MB headless Chromium)."
echo "  This is what lets the engine collect Instagram follower counts,"
echo "  YouTube Popular view counts and YouTube comments without an API key."
echo

if [ ! -x ".venv/bin/python" ]; then
  PY=""
  for c in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
  [ -z "$PY" ] && { echo "  [X] Python 3.10+ not found."; exit 1; }
  "$PY" -m venv .venv
  .venv/bin/python -m pip install -r requirements-dev.txt --quiet
  touch .venv/.installed
fi

.venv/bin/python -m pip install playwright --quiet
.venv/bin/python -m playwright install chromium

echo
echo "  Done. BROWSER_MODE is \"auto\" in .env, so the engine will use it"
echo "  automatically whenever the cheaper methods come back empty."
