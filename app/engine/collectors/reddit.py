"""Reddit profile collector — public about.json + submitted listing.

Official JSON listings, no login. Karma is a score, not followers or reach.
Profile ``subreddit.subscribers`` is Reddit's own follower field for the
user profile; it is copied only from that field and labelled Reddit.
Listing length is not treated as total posts.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.engine.http import fetch
from app.schemas import ContentItem, PlatformAccount

_JSON_HDR = {"Accept": "application/json"}
_KARMA_NOTE = (
    "Karma totals are Reddit scores, not follower counts, impressions, or reach."
)
_FOLLOWERS_NOTE = (
    "Follower count came from Reddit about.json profile subscribers, "
    "not from Instagram or YouTube."
)
_POSTS_NOTE = (
    "Recent posts came from Reddit's public submitted listing. "
    "Listing length is not total post count."
)


def about_url(handle: str) -> str:
    return f"https://www.reddit.com/user/{handle}/about.json"


def submitted_url(handle: str) -> str:
    return f"https://www.reddit.com/user/{handle}/submitted.json?limit=8"


def parse_about(payload: dict) -> dict[str, Any]:
    """Copy identity fields from about.json. Karma is never treated as followers."""
    row = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(row, dict):
        return {}
    name = str(row.get("name") or "").strip()
    if not name:
        return {}
    sub = row.get("subreddit") if isinstance(row.get("subreddit"), dict) else {}
    subscribers = sub.get("subscribers")
    followers = subscribers if isinstance(subscribers, int) and subscribers > 0 else None
    karma = row.get("total_karma")
    return {
        "name": name,
        "title": str(sub.get("title") or "").strip(),
        "description": str(sub.get("public_description") or "").strip(),
        "followers": followers,
        "total_karma": karma if isinstance(karma, int) else None,
        "link_karma": row.get("link_karma") if isinstance(row.get("link_karma"), int) else None,
        "comment_karma": (row.get("comment_karma")
                          if isinstance(row.get("comment_karma"), int) else None),
    }


def parse_submitted(payload: dict) -> list[dict[str, Any]]:
    """Copy recent posts. Score is votes, never views."""
    listing = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(listing, dict):
        return []
    out: list[dict[str, Any]] = []
    for child in listing.get("children") or []:
        if not isinstance(child, dict) or child.get("kind") not in (None, "t3"):
            continue
        row = child.get("data") if isinstance(child.get("data"), dict) else None
        if not row:
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        permalink = str(row.get("permalink") or "")
        url = (f"https://www.reddit.com{permalink}" if permalink.startswith("/")
               else str(row.get("url") or "") or None)
        score = row.get("score")
        comments = row.get("num_comments")
        created = row.get("created_utc")
        published_at = None
        if isinstance(created, (int, float)):
            published_at = datetime.fromtimestamp(created, tz=timezone.utc)
        out.append({
            "title": title,
            "url": url,
            "likes": int(score) if isinstance(score, (int, float)) else None,
            "comments": int(comments) if isinstance(comments, (int, float)) else None,
            "published_at": published_at,
        })
        if len(out) >= 8:
            break
    return out


def _load(text: str) -> dict | None:
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return None
    return body if isinstance(body, dict) else None


async def collect(handle: str) -> PlatformAccount:
    ident = (handle or "").strip().lstrip("@")
    page = f"https://www.reddit.com/user/{ident}"
    acc = PlatformAccount(
        platform="reddit", handle=ident, url=page,
        raw={"source": "reddit_about_json"},
    )
    if len(ident) < 2:
        acc.errors.append("empty handle")
        acc.raw["source"] = "url_only"
        return acc

    about_resp = await fetch(about_url(ident), check_robots=False, headers=_JSON_HDR)
    about = parse_about(_load(about_resp.text) or {}) if about_resp.ok else {}
    if about:
        acc.display_name = about.get("title") or about.get("name")
        acc.bio = about.get("description") or None
        acc.followers = about.get("followers")
        for key in ("total_karma", "link_karma", "comment_karma"):
            if about.get(key) is not None:
                acc.raw[key] = about[key]
        if about.get("total_karma") is not None and _KARMA_NOTE not in acc.errors:
            acc.errors.append(_KARMA_NOTE)
        if acc.followers is not None:
            acc.raw["followers_source"] = "reddit_about_json"
            acc.errors.append(_FOLLOWERS_NOTE)
    elif not about_resp.ok:
        acc.errors.append(f"about.json failed (status {about_resp.status})")

    listing = await fetch(submitted_url(ident), check_robots=False, headers=_JSON_HDR)
    posts = parse_submitted(_load(listing.text) or {}) if listing.ok else []
    for row in posts:
        acc.content.append(ContentItem(
            platform="reddit",
            title=row["title"],
            url=row["url"],
            likes=row["likes"],
            comments=row["comments"],
            published_at=row["published_at"],
            kind="post",
            raw={"source": "reddit_submitted_json"},
        ))
    if posts:
        acc.errors.append(_POSTS_NOTE)
    elif not listing.ok:
        acc.errors.append(f"submitted.json failed (status {listing.status})")
    if not about and not posts:
        acc.raw["source"] = "url_only"
    return acc
