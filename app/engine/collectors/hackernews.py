"""Hacker News collector — official Firebase user API.

Official unauthenticated reads (`hacker-news.firebaseio.com/v0/user/{id}` and
`/v0/item/{id}`). Karma is not followers or audience size. The submitted-id
list length is the official submission count, not a scraped story grid.

The login must already be an HN username or user URL. This module never
guesses ``news.ycombinator.com/user?id={instagram-handle}``.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from app.engine.http import fetch
from app.schemas import ContentItem, PlatformAccount

_NOTE = (
    "Karma came from Hacker News' public user API. "
    "It is HN karma, not followers, Instagram reach, or audience size."
)
_ITEM_NOTE = (
    "Recent submissions came from HN's public item API. "
    "Listed stories are not the full submitted count. Points are not views."
)
_USER = re.compile(r"^[A-Za-z0-9_\-]{2,15}$")
_TAGS = re.compile(r"<[^>]+>")


def username_from(value: str) -> str:
    """Profile login from a username or news.ycombinator.com/user?id= URL."""
    text = (value or "").strip().lstrip("@")
    if not text:
        return ""
    if "ycombinator.com" in text.lower() or "user?id=" in text.lower():
        parts = urlparse(text if "://" in text else f"https://{text}")
        if "item" in (parts.path or "").lower():
            return ""
        qid = (parse_qs(parts.query).get("id") or [""])[0].strip()
        text = qid
    if not _USER.fullmatch(text):
        return ""
    return text


def profile_url(login: str) -> str:
    return f"https://news.ycombinator.com/user?id={login}"


def user_api_url(login: str) -> str:
    return f"https://hacker-news.firebaseio.com/v0/user/{quote(login)}.json"


def item_api_url(item_id: int) -> str:
    return f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"


def parse_user(payload: dict) -> dict[str, Any]:
    """Copy public user fields. Karma is not followers."""
    if not isinstance(payload, dict):
        return {}
    login = str(payload.get("id") or "").strip()
    if not login:
        return {}
    about = _TAGS.sub(" ", str(payload.get("about") or "")).strip()
    about = re.sub(r"\s+", " ", about)
    submitted = payload.get("submitted")
    posts = len(submitted) if isinstance(submitted, list) else None
    karma = payload.get("karma")
    created = payload.get("created")
    ids = [n for n in submitted[:8]] if isinstance(submitted, list) else []
    return {
        "login": login,
        "bio": about,
        "posts": posts if isinstance(posts, int) and posts > 0 else None,
        "karma": karma if isinstance(karma, int) and karma > 0 else None,
        "created": created if isinstance(created, int) and created > 0 else None,
        "submitted_ids": [n for n in ids if isinstance(n, int) and n > 0][:5],
    }


def parse_item(payload: dict) -> dict[str, Any]:
    """Copy a story title. score is not views."""
    if not isinstance(payload, dict):
        return {}
    if payload.get("dead") or payload.get("deleted"):
        return {}
    title = str(payload.get("title") or "").strip()
    if not title:
        return {}
    item_id = payload.get("id")
    href = str(payload.get("url") or "").strip()
    page = (f"https://news.ycombinator.com/item?id={item_id}"
            if isinstance(item_id, int) else href)
    published_at = None
    stamp = payload.get("time")
    if isinstance(stamp, int) and stamp > 0:
        published_at = datetime.fromtimestamp(stamp, tz=timezone.utc)
    return {
        "title": title[:220],
        "url": page or href or None,
        "published_at": published_at,
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
        platform="hackernews", handle=login or None,
        url=page or (profile_url(login) if login else ""),
        raw={"source": "hackernews_firebase"},
    )
    if not login:
        acc.errors.append(
            "No Hacker News username or user URL. "
            "A handle is not guessed from Instagram or another network.")
        acc.raw["source"] = "url_only"
        return acc

    acc.handle = login
    acc.url = profile_url(login)
    resp = await fetch(user_api_url(login), check_robots=False)
    prof = parse_user(_load(resp.text) or {}) if resp.ok else {}
    if prof:
        acc.handle = prof["login"] or login
        acc.url = profile_url(acc.handle)
        acc.bio = (prof.get("bio") or "")[:800] or None
        acc.posts = prof.get("posts")
        if prof.get("karma") is not None:
            acc.raw["karma"] = prof["karma"]
        if acc.posts is not None:
            acc.raw["posts_source"] = "hackernews_submitted"
        acc.errors.append(_NOTE)
    elif not resp.ok:
        acc.errors.append(f"user lookup failed (status {resp.status})")
        acc.raw["source"] = "url_only"

    for item_id in prof.get("submitted_ids") or []:
        item_resp = await fetch(item_api_url(item_id), check_robots=False)
        row = parse_item(_load(item_resp.text) or {}) if item_resp.ok else {}
        if not row:
            continue
        acc.content.append(ContentItem(
            platform="hackernews",
            title=row["title"],
            url=row.get("url"),
            published_at=row.get("published_at"),
            kind="post",
            raw={"source": "hackernews_item"},
        ))
    if acc.content:
        acc.errors.append(_ITEM_NOTE)
    if not prof and not acc.content:
        acc.raw["source"] = "url_only"
    return acc
