#!/usr/bin/env bash
# Generate the bundled sample reports. No internet connection is used.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  PY=""
  for c in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
  [ -z "$PY" ] && { echo "  [X] Python 3.10+ not found."; exit 1; }
  "$PY" -m venv .venv
fi
VPY=".venv/bin/python"
if [ ! -f ".venv/.installed" ]; then
  "$VPY" -m pip install --upgrade pip --quiet
  "$VPY" -m pip install -r requirements-dev.txt --quiet
  touch .venv/.installed
fi
"$VPY" tools/bootstrap.py >/dev/null

"$VPY" scripts_demo.py
echo
echo "  Opening the cohort report..."
for f in data/samples/cohort.html data/samples/sunil_panda.html; do
  if command -v open >/dev/null; then open "$f"
  elif command -v xdg-open >/dev/null; then xdg-open "$f"
  fi
done
echo "  All samples are in: $(pwd)/data/samples"
