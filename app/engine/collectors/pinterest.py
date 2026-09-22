"""Pinterest collector — official oEmbed only.

oEmbed returns author name, title, and thumbnail. It does not include
follower counts, monthly viewers, or a pin grid. Those stay unavailable.

The login must already be a Pinterest username or profile URL. This module
never guesses ``pinterest.com/{instagram-handle}``.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from app.engine.http import fetch
from app.schemas import PlatformAccount

_NOTE = (
    "Pinterest oEmbed does not include follower or pin counts; those stay unavailable."
)
_USER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,29}$")
_PROFILE = re.compile(
    r"pinterest\.(?:com|[a-z]{2}(?:\.[a-z]{2})?)/([A-Za-z0-9][A-Za-z0-9._-]{2,29})/?$",
    re.I,
)
RESERVED = frozenset({
    "about", "business", "categories", "following", "ideas", "login",
    "newsroom", "pin", "pins", "resource", "search", "settings", "shop",
    "signup", "today", "videos",
})


def username_from(value: str) -> str:
    """Profile login from a username or pinterest.com/{user} URL. Pins stay empty."""
    text = (value or "").strip().lstrip("@")
    if not text:
        return ""
    if "pinterest." in text.lower():
        match = _PROFILE.search(text.split("?")[0].rstrip("/"))
        if not match:
            return ""
        text = match.group(1)
    if text.lower() in RESERVED or not _USER.fullmatch(text):
        return ""
    return text


def profile_url(login: str) -> str:
    return f"https://www.pinterest.com/{login}/"


def oembed_url(page: str) -> str:
    return f"https://www.pinterest.com/oembed.json?url={quote(page, safe='')}"


def parse_oembed(payload: dict) -> dict[str, Any]:
    """Copy the fields Pinterest published. No invented metrics."""
    if not isinstance(payload, dict):
        return {}
    name = str(payload.get("author_name") or "").strip()
    title = str(payload.get("title") or "").strip()
    author_url = str(payload.get("author_url") or "").strip()
    thumb = str(payload.get("thumbnail_url") or "").strip()
    if not (name or title):
        return {}
    return {
        "display_name": name or title,
        "bio": title or name,
        "author_url": author_url,
        "thumbnail": thumb,
    }


def _load(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def collect(handle: str, *, url: str | None = None) -> PlatformAccount:
    login = username_from(handle) or username_from(url or "")
    page = url or (profile_url(login) if login else handle or "")
    acc = PlatformAccount(
        platform="pinterest", handle=login or None,
        url=page or (profile_url(login) if login else ""),
        raw={"source": "pinterest_oembed"},
    )
    if not login:
        acc.errors.append(
            "No Pinterest username or profile URL. "
            "A handle is not guessed from Instagram or another network.")
        acc.raw["source"] = "url_only"
        return acc

    acc.handle = login
    acc.url = profile_url(login)
    resp = await fetch(oembed_url(acc.url), check_robots=False)
    fields = parse_oembed(_load(resp.text) or {}) if resp.ok else {}
    if fields:
        acc.display_name = fields.get("display_name") or None
        acc.bio = (fields.get("bio") or "")[:800] or None
        if fields.get("thumbnail"):
            acc.raw["thumbnail"] = fields["thumbnail"]
        if fields.get("author_url"):
            acc.raw["author_url"] = fields["author_url"]
        acc.errors.append(_NOTE)
    else:
        acc.raw["source"] = "url_only"
        if not resp.ok:
            acc.errors.append(f"oEmbed failed (status {resp.status})")
        else:
            acc.errors.append("Pinterest oEmbed returned no author or title.")
        acc.errors.append(_NOTE)
    return acc
