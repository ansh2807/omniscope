#!/usr/bin/env python3
"""First-run setup. Idempotent — safe to run on every launch.

Creates .env from the template if missing, replaces the placeholder API key with a real
random one, ensures the data directories exist, and prints the active key on the last
line of stdout so the launcher can open the browser already signed in.
"""
from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV, TEMPLATE = ROOT / ".env", ROOT / ".env.example"
PLACEHOLDER = "dev-key-change-me"


def main() -> int:
    if not ENV.exists():
        if not TEMPLATE.exists():
            print("ERROR: neither .env nor .env.example found", file=sys.stderr)
            return 1
        ENV.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
        print("  created .env from .env.example", file=sys.stderr)

    text = ENV.read_text(encoding="utf-8")
    m = re.search(r'^API_KEYS\s*=\s*"?([^"\n]*)"?\s*$', text, re.M)
    current = (m.group(1).strip() if m else "")

    if not current or current == PLACEHOLDER:
        key = secrets.token_urlsafe(24)
        if m:
            text = text[:m.start()] + f'API_KEYS="{key}"' + text[m.end():]
        else:
            text += f'\nAPI_KEYS="{key}"\n'
        ENV.write_text(text, encoding="utf-8")
        print(f"  generated a private API key and saved it to .env", file=sys.stderr)
    else:
        key = current.split(",")[0].strip()

    for d in ("data", "data/reports", "data/cache"):
        (ROOT / d).mkdir(parents=True, exist_ok=True)

    # Warn about the one config mistake that actually breaks things on Windows.
    low = str(ROOT).lower()
    if any(x in low for x in ("onedrive", "dropbox", "google drive", "icloud")):
        print("  WARNING: this folder is inside a cloud-synced directory. SQLite locking",
              file=sys.stderr)
        print("           fails there. Move the project to e.g. C:\\creator-intel, or set",
              file=sys.stderr)
        print("           DATABASE_URL in .env to a local path.", file=sys.stderr)

    print(key)          # last line of stdout — the launcher reads this
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
