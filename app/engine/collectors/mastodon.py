"""Mastodon collector — public instance lookup and statuses.

Official unauthenticated Mastodon/Akkoma reads (`/api/v1/accounts/lookup` and
`/api/v1/accounts/{id}/statuses`). Follower and favourite counts are instance
tallies, not impressions. Feed length is not total posts.

The handle must already be an acct (`user@instance`) or a profile URL. This
module never guesses `instagram-handle@mastodon.social`.
"""
from __future__ import annotations

import json
import re
from datetime import timezone
from typing import Any
from urllib.parse import quote, urlparse

from dateutil import parser as dateparser

from app.engine.http import fetch
from app.schemas import ContentItem, PlatformAccount

_NOTE = (
    "Follower and favourite counts came from the instance's public API. "
    "They are not impressions, reach, or audience demographics."
)
_FEED_NOTE = (
    "Recent posts came from the instance's public statuses API. "
    "Feed length is not total post count."
)
_ACCT = re.compile(
    r"^@?([A-Za-z0-9_\.]{1,30})@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})$",
)
_URL = re.compile(
    r"^https?://([^/]+)/@([A-Za-z0-9_\.]{1,30})/?$",
    re.I,
)
_USERS = re.compile(
    r"^https?://([^/]+)/users/([A-Za-z0-9_\.]{1,30})/?$",
    re.I,
)
NOT_MASTODON = frozenset({
    "instagram.com", "threads.net", "threads.com", "tiktok.com",
    "youtube.com", "medium.com", "x.com", "twitter.com", "bsky.app",
    "facebook.com", "linkedin.com", "reddit.com", "substack.com",
    "github.com", "soundcloud.com", "pinterest.com", "news.ycombinator.com",
    "snapchat.com",
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
    "proton.me", "googlemail.com",
})
KNOWN_INSTANCES = frozenset({
    "mastodon.social", "mastodon.online", "mstdn.social", "fosstodon.org",
    "hachyderm.io", "mas.to",
})


def _denied(host: str) -> bool:
    host = (host or "").lower().removeprefix("www.")
    return host in NOT_MASTODON or any(host.endswith("." + item) for item in NOT_MASTODON)


def _acct_host_ok(instance: str, *, loose: bool) -> bool:
    host = (instance or "").lower()
    if _denied(host):
        return False
    if loose:
        return True
    return host in KNOWN_INSTANCES or "mastodon" in host


def parse_acct(value: str, *, loose: bool = True) -> tuple[str, str]:
    """Return (user, instance) from an acct or profile URL. Empty if not Mastodon.

    Bare ``user@host`` emails stay empty unless *loose* or the host is a known
    instance. Profile URLs still use the denylist only.
    """
    text = (value or "").strip()
    if not text:
        return "", ""
    match = _ACCT.fullmatch(text)
    if match and _acct_host_ok(match.group(2), loose=loose):
        return match.group(1), match.group(2).lower()
    if text.startswith("@") and text.count("@") == 2:
        match = _ACCT.fullmatch(text[1:])
        if match and _acct_host_ok(match.group(2), loose=loose):
            return match.group(1), match.group(2).lower()
    if "://" not in text and text.startswith("//"):
        text = "https:" + text
    if "://" not in text and "/" in text:
        text = "https://" + text.lstrip("/")
    match = _URL.fullmatch(text) or _USERS.fullmatch(text)
    if match and not _denied(match.group(1)):
        return match.group(2), match.group(1).lower().removeprefix("www.")
    return "", ""


def profile_page(user: str, instance: str) -> str:
    return f"https://{instance}/@{user}"


def profile_from_claim(value: str) -> str:
    """Wikidata P4033 → profile URL, or empty if the claim is not an acct."""
    user, instance = parse_acct(value)
    if user and instance:
        return profile_page(user, instance)
    return ""


def lookup_url(user: str, instance: str) -> str:
    return f"https://{instance}/api/v1/accounts/lookup?acct={quote(user)}"


def statuses_url(instance: str, account_id: str) -> str:
    return (f"https://{instance}/api/v1/accounts/{quote(account_id)}/statuses"
            "?exclude_replies=true&exclude_reblogs=true&limit=8")


def parse_profile(payload: dict) -> dict[str, Any]:
    """Copy public account fields. Missing counts stay missing."""
    if not isinstance(payload, dict):
        return {}
    acct = str(payload.get("acct") or "").strip()
    ident = str(payload.get("id") or "").strip()
    if not ident:
        return {}
    followers = payload.get("followers_count")
    following = payload.get("following_count")
    posts = payload.get("statuses_count")
    return {
        "id": ident,
        "acct": acct,
        "display_name": str(payload.get("display_name") or "").strip(),
        "bio": re.sub(r"<[^>]+>", " ", str(payload.get("note") or "")).strip(),
        "url": str(payload.get("url") or "").strip(),
        "followers": followers if isinstance(followers, int) and followers > 0 else None,
        "following": following if isinstance(following, int) and following > 0 else None,
        "posts": posts if isinstance(posts, int) and posts > 0 else None,
    }


def parse_statuses(payload: list | dict) -> list[dict[str, Any]]:
    """Copy recent post text. favourites are likes, never views."""
    rows = payload if isinstance(payload, list) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = re.sub(r"<[^>]+>", " ", str(row.get("content") or "")).strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        likes = row.get("favourites_count")
        replies = row.get("replies_count")
        created = str(row.get("created_at") or "")
        published_at = None
        if created:
            try:
                published_at = dateparser.parse(created)
            except (ValueError, OverflowError, TypeError):
                published_at = None
            if published_at is not None and published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
        out.append({
            "title": text[:220],
            "url": str(row.get("url") or "").strip() or None,
            "likes": likes if isinstance(likes, int) else None,
            "comments": replies if isinstance(replies, int) else None,
            "published_at": published_at,
        })
        if len(out) >= 8:
            break
    return out


def _load(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def collect(handle: str, *, url: str | None = None) -> PlatformAccount:
    user, instance = parse_acct(handle) if handle else ("", "")
    if not user and url:
        user, instance = parse_acct(url)
    page = url or (profile_page(user, instance) if user and instance else handle or "")
    if page and not page.startswith("http"):
        page = profile_page(user, instance) if user and instance else f"https://{page}"
    ident = f"{user}@{instance}" if user and instance else (handle or "").strip()
    acc = PlatformAccount(
        platform="mastodon", handle=ident or None, url=page or ident,
        raw={"source": "mastodon_public_api"},
    )
    if not user or not instance:
        acc.errors.append(
            "No Mastodon acct or profile URL. "
            "A handle is not guessed from Instagram or another network.")
        acc.raw["source"] = "url_only"
        return acc
    if _denied(instance):
        acc.errors.append(f"{instance} is not treated as a Mastodon instance.")
        acc.raw["source"] = "url_only"
        return acc

    acc.url = profile_page(user, instance)
    acc.handle = f"{user}@{instance}"
    prof_resp = await fetch(lookup_url(user, instance), check_robots=False)
    prof = parse_profile(_load(prof_resp.text) or {}) if prof_resp.ok else {}
    if prof:
        acc.display_name = prof.get("display_name") or None
        bio = re.sub(r"\s+", " ", prof.get("bio") or "").strip()
        acc.bio = bio[:800] or None
        acc.followers = prof.get("followers")
        acc.following = prof.get("following")
        acc.posts = prof.get("posts")
        if prof.get("url"):
            parsed = urlparse(prof["url"])
            if parsed.scheme in ("http", "https") and parsed.netloc:
                acc.url = prof["url"]
        acc.raw["account_id"] = prof["id"]
        if acc.followers is not None:
            acc.raw["followers_source"] = "mastodon_public_api"
        acc.errors.append(_NOTE)
    elif not prof_resp.ok:
        acc.errors.append(f"accounts/lookup failed (status {prof_resp.status})")
        acc.raw["source"] = "url_only"

    account_id = (prof or {}).get("id") or ""
    if account_id:
        feed_resp = await fetch(statuses_url(instance, account_id), check_robots=False)
        posts = parse_statuses(_load(feed_resp.text) or []) if feed_resp.ok else []
        for row in posts:
            acc.content.append(ContentItem(
                platform="mastodon",
                title=row["title"],
                url=row.get("url"),
                likes=row.get("likes"),
                comments=row.get("comments"),
                published_at=row.get("published_at"),
                kind="post",
                raw={"source": "mastodon_public_statuses"},
            ))
        if posts:
            acc.errors.append(_FEED_NOTE)
        elif not feed_resp.ok:
            acc.errors.append(f"accounts/statuses failed (status {feed_resp.status})")
    if not prof and not acc.content:
        acc.raw["source"] = "url_only"
    return acc
