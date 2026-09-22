"""TikTok collector — official oEmbed only.

oEmbed returns author name, title, and thumbnail. It does not include
follower counts, video views, or a post grid. Those stay unavailable.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from app.engine.http import fetch
from app.schemas import PlatformAccount

_NOTE = (
    "TikTok oEmbed does not include follower or view counts; those stay unavailable."
)


def oembed_url(profile_url: str) -> str:
    return f"https://www.tiktok.com/oembed?url={quote(profile_url, safe='')}"


def parse_oembed(payload: dict) -> dict[str, Any]:
    """Copy the fields TikTok published. No invented metrics."""
    if not isinstance(payload, dict):
        return {}
    name = str(payload.get("author_name") or "").strip()
    title = str(payload.get("title") or "").strip()
    author_url = str(payload.get("author_url") or "").strip()
    thumb = str(payload.get("thumbnail_url") or "").strip()
    if not (name or title):
        return {}
    return {
        "display_name": name,
        "title": title,
        "author_url": author_url,
        "thumbnail": thumb,
    }


async def collect(handle: str) -> PlatformAccount:
    ident = (handle or "").strip().lstrip("@")
    page = f"https://www.tiktok.com/@{ident}"
    acc = PlatformAccount(
        platform="tiktok", handle=ident, url=page,
        raw={"source": "tiktok_oembed"},
    )
    if len(ident) < 2:
        acc.errors.append("empty handle")
        acc.raw["source"] = "url_only"
        return acc

    resp = await fetch(oembed_url(page), check_robots=False)
    body = None
    if resp.ok and resp.text.strip().startswith("{"):
        try:
            parsed = json.loads(resp.text)
        except json.JSONDecodeError:
            parsed = None
        body = parsed if isinstance(parsed, dict) else None
    fields = parse_oembed(body or {})
    if fields:
        acc.display_name = fields.get("display_name") or None
        acc.bio = fields.get("title") or None
        if fields.get("thumbnail"):
            acc.raw["thumbnail"] = fields["thumbnail"]
        if fields.get("author_url"):
            acc.raw["author_url"] = fields["author_url"]
    else:
        acc.raw["source"] = "url_only"
        if not resp.ok:
            acc.errors.append(f"oEmbed failed (status {resp.status})")
        else:
            acc.errors.append("TikTok oEmbed returned no author or title.")
    acc.errors.append(_NOTE)
    return acc
