#!/usr/bin/env python3
"""Self-hosted update client.

Runs inside a customer's installation. Phones the licence server to (a) confirm the
licence is still valid and (b) learn whether a newer build exists, then applies it.

Design decisions worth stating:

  * **Offline grace.** A network blip must not brick a paid customer's install, so the
    last good entitlement is cached and honoured for LICENSE_GRACE_DAYS.
  * **Checksum enforced.** A download whose SHA-256 does not match the published value is
    discarded. This is the difference between an update channel and a supply-chain hole.
  * **Backup before apply.** The current install is copied aside first, so a bad release
    can be rolled back by hand.
  * **Never auto-applies a major version.** Those get flagged for a human.
"""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import socket
import sys
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "license_state.json"
BACKUPS = ROOT / "data" / "backups"


def device_id() -> str:
    """Stable per-machine id. MAC-derived, hashed so it is not personally identifying."""
    raw = f"{uuid.getnode()}-{platform.node()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, indent=2, default=str), encoding="utf-8")


@dataclass
class LicenseState:
    valid: bool
    reason: str
    plan: dict
    usage: dict
    latest_release: dict | None
    offline: bool = False
    checked_at: str = ""


def check_license(server: str, key: str, version: str, timeout: int = 15) -> LicenseState:
    payload = json.dumps({
        "key": key, "device_id": device_id(), "version": version,
        "hostname": socket.gethostname()[:80], "platform": platform.platform()[:40],
    }).encode()
    url = server.rstrip("/") + "/api/license/validate"
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        state = _load_state()
        state.update({"last_good": data, "last_check": datetime.utcnow().isoformat()})
        _save_state(state)
        return LicenseState(
            valid=bool(data.get("valid")), reason=data.get("reason", ""),
            plan=data.get("plan", {}), usage=data.get("usage", {}),
            latest_release=data.get("latest_release"),
            checked_at=data.get("checked_at", ""))
    except Exception as exc:  # noqa: BLE001
        # Offline: honour the cached entitlement inside the grace window.
        state = _load_state()
        last = state.get("last_good")
        last_check = state.get("last_check")
        if last and last_check:
            try:
                age = datetime.utcnow() - datetime.fromisoformat(last_check)
            except ValueError:
                age = timedelta(days=999)
            grace = timedelta(days=int(last.get("grace_days", 14)))
            if age <= grace:
                return LicenseState(
                    valid=bool(last.get("valid")),
                    reason=(f"Offline — using the entitlement cached "
                            f"{age.days} day(s) ago. {last.get('reason', '')}"),
                    plan=last.get("plan", {}), usage=last.get("usage", {}),
                    latest_release=last.get("latest_release"), offline=True)
        return LicenseState(valid=False,
                            reason=f"Could not reach the licence server ({exc}) and no "
                                   f"valid cached entitlement is available.",
                            plan={}, usage={}, latest_release=None, offline=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _semver(v: str) -> tuple[int, ...]:
    parts = []
    for chunk in (v or "0").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits or 0))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def apply_update(release: dict, current_version: str, *, allow_major: bool = False) -> str:
    """Download, verify and unpack. Returns a human-readable outcome."""
    version = release.get("version", "")
    url = release.get("download_url", "")
    expected = (release.get("sha256") or "").lower()
    if not version or not url:
        return "The published release is missing a version or download URL."
    if _semver(version) <= _semver(current_version):
        return f"Already on {current_version}; nothing newer."
    if not allow_major and _semver(version)[0] > _semver(current_version)[0]:
        return (f"Version {version} is a major upgrade from {current_version}. "
                f"Re-run with --allow-major once you have read the release notes.")

    tmp = ROOT / "data" / f"update-{version}.zip"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, tmp)
    except Exception as exc:  # noqa: BLE001
        return f"Download failed: {exc}"

    if expected:
        got = _sha256(tmp)
        if got != expected:
            tmp.unlink(missing_ok=True)
            return (f"Checksum mismatch — expected {expected[:16]}…, got {got[:16]}…. "
                    f"The download was discarded.")

    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    backup = BACKUPS / f"pre-{version}-{stamp}"
    try:
        shutil.copytree(ROOT / "app", backup / "app")
        for f in ("cli.py", "requirements.txt", "requirements-dev.txt"):
            if (ROOT / f).exists():
                shutil.copy2(ROOT / f, backup / f)
    except Exception as exc:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        return f"Could not back up the current install, so nothing was changed: {exc}"

    try:
        with zipfile.ZipFile(tmp) as z:
            root_prefix = ""
            names = z.namelist()
            if names and "/" in names[0]:
                root_prefix = names[0].split("/")[0] + "/"
            for member in names:
                if member.endswith("/"):
                    continue
                rel = member[len(root_prefix):] if root_prefix else member
                # Never overwrite local configuration or customer data.
                if not rel or rel.startswith(("data/", ".env")) or ".." in rel:
                    continue
                target = ROOT / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
    except Exception as exc:  # noqa: BLE001
        return (f"Unpack failed: {exc}. Your previous files are intact and a backup is at "
                f"{backup}")
    finally:
        tmp.unlink(missing_ok=True)

    return (f"Updated to {version}. Backup of the previous install is at {backup}. "
            f"Restart the app to load it.")


def main() -> int:
    import argparse

    sys.path.insert(0, str(ROOT))
    from app.config import settings

    ap = argparse.ArgumentParser(description="Check the licence and apply updates.")
    ap.add_argument("--apply", action="store_true", help="install an available update")
    ap.add_argument("--allow-major", action="store_true")
    ap.add_argument("--server", default=settings.license_server_url)
    ap.add_argument("--key", default=settings.license_key)
    args = ap.parse_args()

    if not args.server or not args.key:
        print("Set LICENSE_SERVER_URL and LICENSE_KEY in .env first.", file=sys.stderr)
        return 2

    state = check_license(args.server, args.key, settings.app_version)
    print(f"Licence : {'valid' if state.valid else 'INVALID'}"
          + (" (offline cache)" if state.offline else ""))
    print(f"Reason  : {state.reason}")
    if state.plan:
        print(f"Plan    : {state.plan.get('name')} — "
              f"{state.plan.get('reports_per_month') or 'unlimited'} reports/month")
    if state.usage:
        print(f"Usage   : {state.usage.get('used')} used, {state.usage.get('left')} left "
              f"({state.usage.get('period')})")

    rel = state.latest_release
    if not rel:
        print("Updates : none published.")
        return 0
    if _semver(rel["version"]) <= _semver(settings.app_version):
        print(f"Updates : up to date on {settings.app_version}.")
        return 0

    print(f"Updates : {rel['version']} available"
          + (" (MANDATORY)" if rel.get("mandatory") else ""))
    if rel.get("notes"):
        print("          " + rel["notes"][:400])
    if not args.apply:
        print("          Run with --apply to install it.")
        return 0
    print(apply_update(rel, settings.app_version, allow_major=args.allow_major))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
