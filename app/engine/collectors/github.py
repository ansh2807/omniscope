"""GitHub collector — public user API.

Official unauthenticated reads (`api.github.com/users/{login}` and
`/users/{login}/repos`). Follower counts are GitHub followers, not Instagram
or YouTube. Star counts are not views or likes. Repo-list length is not
``public_repos``.

The login must already be a GitHub username or profile URL. This module never
guesses ``github.com/{instagram-handle}``.
"""
from __future__ import annotations

import json
import re
from datetime import timezone
from typing import Any
from urllib.parse import quote

from dateutil import parser as dateparser

from app.engine.http import fetch
from app.schemas import ContentItem, PlatformAccount

_NOTE = (
    "Follower counts came from GitHub's public user API. "
    "They are GitHub followers, not Instagram, YouTube, or audience size."
)
_REPO_NOTE = (
    "Recent repositories came from GitHub's public repos list. "
    "List length is not total public_repos. Star counts are not views."
)
_USER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9\-]{0,37}[A-Za-z0-9])?$")
_PROFILE = re.compile(
    r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9\-]{0,37}[A-Za-z0-9])?)/?$",
    re.I,
)
RESERVED = frozenset({
    "about", "account", "blog", "collections", "customer-stories",
    "enterprise", "events", "explore", "features", "gist", "issues",
    "login", "logout", "marketplace", "new", "notifications", "orgs",
    "organizations", "pricing", "pulls", "search", "security", "settings",
    "signup", "sponsors", "topics", "trending", "users",
})


def username_from(value: str) -> str:
    """Profile login from a username or github.com/{user} URL. Repos stay empty."""
    text = (value or "").strip().lstrip("@")
    if not text:
        return ""
    if "github.com/" in text.lower():
        match = _PROFILE.search(text.split("?")[0].rstrip("/"))
        if not match:
            return ""
        text = match.group(1)
    if text.lower() in RESERVED or not _USER.fullmatch(text):
        return ""
    return text


def profile_url(login: str) -> str:
    return f"https://github.com/{login}"


def user_api_url(login: str) -> str:
    return f"https://api.github.com/users/{quote(login)}"


def repos_api_url(login: str) -> str:
    return (f"https://api.github.com/users/{quote(login)}/repos"
            "?sort=updated&per_page=8&type=owner")


def parse_profile(payload: dict) -> dict[str, Any]:
    """Copy public user fields. Missing counts stay missing."""
    if not isinstance(payload, dict):
        return {}
    login = str(payload.get("login") or "").strip()
    if not login:
        return {}
    followers = payload.get("followers")
    following = payload.get("following")
    repos = payload.get("public_repos")
    return {
        "login": login,
        "display_name": str(payload.get("name") or "").strip(),
        "bio": str(payload.get("bio") or "").strip(),
        "url": str(payload.get("html_url") or "").strip(),
        "followers": followers if isinstance(followers, int) and followers > 0 else None,
        "following": following if isinstance(following, int) and following > 0 else None,
        "posts": repos if isinstance(repos, int) and repos > 0 else None,
    }


def parse_repos(payload: list | dict) -> list[dict[str, Any]]:
    """Copy owned repo names. stargazers_count is not views or likes."""
    rows = payload if isinstance(payload, list) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("fork") is True:
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        desc = str(row.get("description") or "").strip()
        title = f"{name} — {desc}" if desc else name
        updated = str(row.get("updated_at") or row.get("pushed_at") or "")
        published_at = None
        if updated:
            try:
                published_at = dateparser.parse(updated)
            except (ValueError, OverflowError, TypeError):
                published_at = None
            if published_at is not None and published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
        out.append({
            "title": title[:220],
            "url": str(row.get("html_url") or "").strip() or None,
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
    login = username_from(handle) or username_from(url or "")
    page = url or (profile_url(login) if login else handle or "")
    acc = PlatformAccount(
        platform="github", handle=login or None,
        url=page or (profile_url(login) if login else ""),
        raw={"source": "github_public_api"},
    )
    if not login:
        acc.errors.append(
            "No GitHub username or profile URL. "
            "A handle is not guessed from Instagram or another network.")
        acc.raw["source"] = "url_only"
        return acc

    acc.handle = login
    acc.url = profile_url(login)
    prof_resp = await fetch(user_api_url(login), check_robots=False)
    prof = parse_profile(_load(prof_resp.text) or {}) if prof_resp.ok else {}
    if prof:
        acc.handle = prof["login"] or login
        acc.url = prof.get("url") or profile_url(acc.handle)
        acc.display_name = prof.get("display_name") or None
        acc.bio = (prof.get("bio") or "")[:800] or None
        acc.followers = prof.get("followers")
        acc.following = prof.get("following")
        acc.posts = prof.get("posts")
        if acc.followers is not None:
            acc.raw["followers_source"] = "github_public_api"
        if acc.posts is not None:
            acc.raw["posts_source"] = "github_public_repos"
        acc.errors.append(_NOTE)
    elif not prof_resp.ok:
        acc.errors.append(f"users lookup failed (status {prof_resp.status})")
        acc.raw["source"] = "url_only"

    repos_resp = await fetch(repos_api_url(acc.handle or login), check_robots=False)
    repos = parse_repos(_load(repos_resp.text) or []) if repos_resp.ok else []
    for row in repos:
        acc.content.append(ContentItem(
            platform="github",
            title=row["title"],
            url=row.get("url"),
            published_at=row.get("published_at"),
            kind="post",
            raw={"source": "github_public_repos"},
        ))
    if repos:
        acc.errors.append(_REPO_NOTE)
    elif prof and not repos_resp.ok:
        acc.errors.append(f"repos list failed (status {repos_resp.status})")
    if not prof and not repos:
        acc.raw["source"] = "url_only"
    return acc
