"""Bluesky collector — public AppView profile and author feed.

Official unauthenticated AppView reads (`public.api.bsky.app`). Follower and
like counts are AppView tallies, not impressions or reach. Feed length is not
total posts.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from dateutil import parser as dateparser

from app.engine.http import fetch
from app.schemas import ContentItem, PlatformAccount

_PROFILE = "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile"
_FEED = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
_NOTE = (
    "Follower and like counts came from Bluesky's public AppView. "
    "They are not impressions, reach, or audience demographics."
)
_FEED_NOTE = (
    "Recent posts came from Bluesky's public author feed. "
    "Feed length is not total post count."
)


def profile_url(handle: str) -> str:
    return f"{_PROFILE}?actor={quote(handle)}"


def feed_url(handle: str) -> str:
    return f"{_FEED}?actor={quote(handle)}&limit=8&filter=posts_no_replies"


def parse_profile(payload: dict) -> dict[str, Any]:
    """Copy AppView profile fields. Missing counts stay missing."""
    if not isinstance(payload, dict):
        return {}
    handle = str(payload.get("handle") or "").strip()
    if not handle:
        return {}
    followers = payload.get("followersCount")
    following = payload.get("followsCount")
    posts = payload.get("postsCount")
    return {
        "handle": handle,
        "display_name": str(payload.get("displayName") or "").strip(),
        "bio": str(payload.get("description") or "").strip(),
        "did": str(payload.get("did") or "").strip(),
        "followers": followers if isinstance(followers, int) and followers > 0 else None,
        "following": following if isinstance(following, int) and following > 0 else None,
        "posts": posts if isinstance(posts, int) and posts > 0 else None,
    }


def _post_web_url(handle: str, uri: str) -> str | None:
    # at://did:plc:…/app.bsky.feed.post/{rkey}
    parts = [p for p in (uri or "").split("/") if p]
    if len(parts) >= 3 and parts[-2] == "app.bsky.feed.post":
        return f"https://bsky.app/profile/{handle}/post/{parts[-1]}"
    return None


def parse_feed(payload: dict, *, handle: str) -> list[dict[str, Any]]:
    """Copy recent post text. likeCount is likes, never views."""
    rows = payload.get("feed") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        post = row.get("post") if isinstance(row, dict) else None
        if not isinstance(post, dict):
            continue
        record = post.get("record") if isinstance(post.get("record"), dict) else {}
        text = str(record.get("text") or "").strip()
        if not text:
            continue
        likes = post.get("likeCount")
        replies = post.get("replyCount")
        created = str(record.get("createdAt") or post.get("indexedAt") or "")
        published_at = None
        if created:
            try:
                published_at = dateparser.parse(created)
            except (ValueError, OverflowError, TypeError):
                published_at = None
            if published_at and published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
        uri = str(post.get("uri") or "")
        out.append({
            "title": text[:220],
            "url": _post_web_url(handle, uri),
            "likes": likes if isinstance(likes, int) else None,
            "comments": replies if isinstance(replies, int) else None,
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
    page = f"https://bsky.app/profile/{ident}"
    acc = PlatformAccount(
        platform="bluesky", handle=ident, url=page,
        raw={"source": "bluesky_appview"},
    )
    if len(ident) < 3:
        acc.errors.append("empty handle")
        acc.raw["source"] = "url_only"
        return acc

    prof_resp = await fetch(profile_url(ident), check_robots=False)
    prof = parse_profile(_load(prof_resp.text) or {}) if prof_resp.ok else {}
    if prof:
        acc.handle = prof["handle"] or ident
        acc.url = f"https://bsky.app/profile/{acc.handle}"
        acc.display_name = prof.get("display_name") or None
        acc.bio = prof.get("bio") or None
        acc.followers = prof.get("followers")
        acc.following = prof.get("following")
        acc.posts = prof.get("posts")
        if prof.get("did"):
            acc.raw["did"] = prof["did"]
        if acc.followers is not None:
            acc.raw["followers_source"] = "bluesky_appview"
        acc.errors.append(_NOTE)
    elif not prof_resp.ok:
        acc.errors.append(f"getProfile failed (status {prof_resp.status})")
        acc.raw["source"] = "url_only"

    feed_resp = await fetch(feed_url(acc.handle), check_robots=False)
    posts = parse_feed(_load(feed_resp.text) or {}, handle=acc.handle) if feed_resp.ok else []
    for row in posts:
        acc.content.append(ContentItem(
            platform="bluesky",
            title=row["title"],
            url=row["url"],
            likes=row["likes"],
            comments=row["comments"],
            published_at=row["published_at"],
            kind="post",
            raw={"source": "bluesky_author_feed"},
        ))
    if posts:
        acc.errors.append(_FEED_NOTE)
    elif not feed_resp.ok:
        acc.errors.append(f"getAuthorFeed failed (status {feed_resp.status})")
    if not prof and not posts:
        acc.raw["source"] = "url_only"
    return acc
