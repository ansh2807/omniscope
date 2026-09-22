"""Read and write instance keys from the running app.

Project `.env` is preferred on a desktop install. Docker only mounts the data
volume, so we also keep `runtime.env` next to reports (writable, survives
recreate). Nothing that changes the compliance posture is editable here.
"""
from __future__ import annotations

import re
import secrets
from pathlib import Path

from app.config import settings

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"

ALLOWED = {
    "YOUTUBE_API_KEY", "SEARCH_PROVIDER", "SERPER_API_KEY", "BRAVE_API_KEY",
    "GOOGLE_CSE_KEY", "GOOGLE_CSE_CX", "BROWSER_MODE", "PUBLIC_BASE_URL",
    "ADMIN_TOKEN",
}


def runtime_path() -> Path:
    return Path(settings.reports_dir).resolve().parent / "runtime.env"


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _read_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return _parse(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def read() -> dict[str, str]:
    """runtime.env wins over project .env for the same key."""
    merged = _read_file(ENV)
    merged.update(_read_file(runtime_path()))
    return merged


def _merge_text(text: str, updates: dict[str, str]) -> tuple[str, list[str]]:
    changed: list[str] = []
    out = text
    for key, value in updates.items():
        line = f'{key}="{value}"'
        pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.M)
        match = pattern.search(out)
        if match:
            if match.group(0) != line:
                out = pattern.sub(line, out, count=1)
                changed.append(key)
        else:
            out = out.rstrip("\n") + f"\n{line}\n"
            changed.append(key)
    return out, changed


def write(updates: dict[str, str]) -> list[str]:
    """Merge into runtime.env, then project .env. Returns keys that changed."""
    updates = {k: v for k, v in updates.items() if k in ALLOWED}
    if not updates:
        return []
    changed: list[str] = []
    last_error: OSError | None = None
    for path in (runtime_path(), ENV):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            text, keys = _merge_text(text, updates)
            path.write_text(text, encoding="utf-8")
            changed = keys or changed
            last_error = None
            break
        except OSError as exc:
            last_error = exc
    if last_error is not None and not changed:
        raise last_error
    return changed


def apply_to_settings(updates: dict[str, str]) -> None:
    """Hot-apply so search keys work without a process restart."""
    for key, value in updates.items():
        if key not in ALLOWED:
            continue
        attr = key.lower()
        if hasattr(settings, attr):
            setattr(settings, attr, value)


def load_into_settings() -> None:
    apply_to_settings(read())


def ensure_operator_token() -> None:
    """Mint a data-volume token when ADMIN_TOKEN was never set.

    The value is not logged. Read `{reports_dir}/../.operator-token` on the host.
    """
    if settings.admin_token:
        return
    path = Path(settings.reports_dir).resolve().parent / ".operator-token"
    try:
        if path.exists():
            token = path.read_text(encoding="utf-8").strip()
        else:
            token = secrets.token_urlsafe(18)
            path.write_text(token + "\n", encoding="utf-8")
        if token:
            settings.admin_token = token
    except OSError:
        return
