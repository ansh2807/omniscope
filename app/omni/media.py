"""Post / video intelligence from public metadata only (spec §1, §7).

Fetches the URL through the SSRF-safe client. YouTube and TikTok may also
answer official oEmbed (no key). View counts, reach and watch-time are
recorded only when the page publishes them as structured data — never parsed
from decoration.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlparse

from pydantic import BaseModel, Field

from app.engine.collectors.web import _jsonld, _text
from app.omni.webintel import extract_page

ENGINE_VERSION = "0.4.0"


class MediaPayload(BaseModel):
    report_id: str
    generated_at: datetime
    kind: str = "media"
    url: str
    platform: str = "unknown"
    title: str = ""
    description: str = ""
    author: str = ""
    author_url: str = ""
    published: str = ""
    duration: str = ""
    thumbnail: str = ""
    view_count: int | None = None
    upvote_count: int | None = None
    comment_count: int | None = None
    community: str = ""
    word_count: int = 0
    jsonld_types: list[str] = Field(default_factory=list)
    method: str = ""
    assessed: bool = False
    reason: str = ""
    unavailable: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    engine_version: str = ENGINE_VERSION


def platform_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "youtu.be" in host or "youtube.com" in host:
        return "youtube"
    if "instagram.com" in host:
        return "instagram"
    if "tiktok.com" in host:
        return "tiktok"
    if host in {"x.com", "twitter.com"}:
        return "x"
    if "linkedin.com" in host:
        return "linkedin"
    if "facebook.com" in host:
        return "facebook"
    if "reddit.com" in host:
        return "reddit"
    if "bsky.app" in host or host.endswith("bsky.social"):
        return "bluesky"
    return "unknown"


def reddit_json_url(url: str) -> str | None:
    if platform_of(url) != "reddit":
        return None
    path = urlparse(url).path.rstrip("/")
    if "/comments/" not in path:
        return None
    clean = url.split("?")[0].rstrip("/")
    if clean.endswith(".json"):
        return clean
    return clean + ".json"


def _reddit_post(data) -> dict | None:
    listing = data[0] if isinstance(data, list) and data else data
    if not isinstance(listing, dict):
        return None
    children = ((listing.get("data") or {}).get("children") or [])
    for child in children:
        row = child.get("data") if isinstance(child, dict) else None
        if isinstance(row, dict) and row.get("title"):
            return row
    return None


def from_reddit_json(url: str, data) -> MediaPayload:
    """Pure function over Reddit's public listing JSON. No HTML scraping."""
    post = _reddit_post(data)
    if not post:
        return MediaPayload(
            report_id="", generated_at=datetime.now(timezone.utc), url=url,
            platform="reddit", assessed=False,
            reason="Reddit JSON had no post listing.",
            unavailable=[
                {"item": "Engagement rate / reach",
                 "why": "Platform analytics; listing score is not reach."},
            ],
        )
    created = post.get("created_utc")
    published = ""
    if isinstance(created, (int, float)):
        published = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
    score = post.get("score")
    comments = post.get("num_comments")
    unavailable = [
        {"item": "Engagement rate / reach",
         "why": "Listing score is votes on this post, not impressions or reach."},
        {"item": "Audience demographics",
         "why": "Private. Not inferred from the subreddit name."},
    ]
    return MediaPayload(
        report_id="",
        generated_at=datetime.now(timezone.utc),
        url=url,
        platform="reddit",
        title=str(post.get("title") or "")[:300],
        description=str(post.get("selftext") or "")[:800],
        author=str(post.get("author") or "")[:160],
        published=published[:40],
        upvote_count=int(score) if isinstance(score, (int, float)) else None,
        comment_count=int(comments) if isinstance(comments, (int, float)) else None,
        community=str(post.get("subreddit") or "")[:80],
        word_count=len(str(post.get("selftext") or "").split()),
        method="reddit_json",
        assessed=True,
        unavailable=unavailable,
    )


def bluesky_at_uri(url: str) -> str | None:
    parts = urlparse(url)
    host = parts.netloc.lower()
    if "bsky.app" not in host:
        return None
    segs = [s for s in parts.path.split("/") if s]
    if len(segs) >= 4 and segs[0] == "profile" and segs[2] == "post":
        return f"at://{segs[1]}/app.bsky.feed.post/{segs[3]}"
    return None


def bluesky_thread_url(url: str) -> str | None:
    uri = bluesky_at_uri(url)
    if not uri:
        return None
    return ("https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread"
            f"?uri={quote(uri, safe=':/')}&depth=0")


def from_bluesky_thread(url: str, data: dict) -> MediaPayload:
    """Pure function over Bluesky's public AppView JSON. Likes are not reach."""
    thread = data.get("thread") if isinstance(data, dict) else None
    post = (thread or {}).get("post") if isinstance(thread, dict) else None
    if not isinstance(post, dict):
        return MediaPayload(
            report_id="", generated_at=datetime.now(timezone.utc), url=url,
            platform="bluesky", assessed=False,
            reason="Bluesky public API returned no post thread.",
            unavailable=[{"item": "Engagement rate / reach",
                          "why": "AppView like/reply counts are not impressions."}],
        )
    record = post.get("record") if isinstance(post.get("record"), dict) else {}
    author = post.get("author") if isinstance(post.get("author"), dict) else {}
    text = str(record.get("text") or "")
    likes = post.get("likeCount")
    replies = post.get("replyCount")
    return MediaPayload(
        report_id="",
        generated_at=datetime.now(timezone.utc),
        url=url,
        platform="bluesky",
        title=text[:120] or "Bluesky post",
        description=text[:800],
        author=str(author.get("handle") or author.get("displayName") or "")[:160],
        author_url=(f"https://bsky.app/profile/{author.get('handle')}"
                    if author.get("handle") else ""),
        published=str(record.get("createdAt") or "")[:40],
        upvote_count=int(likes) if isinstance(likes, (int, float)) else None,
        comment_count=int(replies) if isinstance(replies, (int, float)) else None,
        word_count=len(text.split()),
        method="bluesky_public_api",
        assessed=bool(text.strip() or author.get("handle")),
        reason="" if text.strip() or author.get("handle") else "Empty Bluesky thread.",
        unavailable=[
            {"item": "Engagement rate / reach",
             "why": "likeCount/replyCount are public tallies, not impressions or reach."},
            {"item": "Audience demographics",
             "why": "Private. Not inferred from the handle."},
        ],
    )


def youtube_oembed_url(url: str) -> str | None:
    if platform_of(url) != "youtube":
        return None
    return f"https://www.youtube.com/oembed?url={quote(url, safe='')}&format=json"


def tiktok_oembed_url(url: str) -> str | None:
    if platform_of(url) != "tiktok":
        return None
    return f"https://www.tiktok.com/oembed?url={quote(url, safe='')}"


def _as_types(entity: dict) -> set[str]:
    raw = entity.get("@type", [])
    if isinstance(raw, str):
        return {raw}
    return set(raw or [])


def _intish(value) -> int | None:
    try:
        return int(str(value).replace(",", "").split(".")[0])
    except (TypeError, ValueError):
        return None


def views_from_jsonld(entities: list[dict]) -> int | None:
    """Watch counts only from interactionStatistic, never from visible copy."""
    for entity in entities:
        if not ({"VideoObject", "SocialMediaPosting"} & _as_types(entity)):
            continue
        stats = entity.get("interactionStatistic") or []
        if isinstance(stats, dict):
            stats = [stats]
        for row in stats:
            if not isinstance(row, dict):
                continue
            types = _as_types(row)
            itype = str(row.get("interactionType") or "")
            if ("WatchAction" in itype or "WatchAction" in types
                    or "UserInteraction" in itype):
                n = _intish(row.get("userInteractionCount"))
                if n is not None:
                    return n
    return None


def from_public_page(url: str, html: str, *, oembed: dict | None = None) -> MediaPayload:
    """Pure function: fetched HTML (+ optional oEmbed JSON) → payload."""
    facts = extract_page(url, html)
    entities = _jsonld(html)
    video = next((e for e in entities if "VideoObject" in _as_types(e)), None)
    oembed = oembed or {}
    title = (oembed.get("title") or (video or {}).get("name")
             or facts.og.get("og:title") or facts.title or "")
    description = ((video or {}).get("description") or facts.og.get("og:description")
                   or facts.meta_description or "")
    author = (oembed.get("author_name") or facts.og.get("og:site_name") or "")
    if isinstance((video or {}).get("author"), dict):
        author = author or str(video.get("author", {}).get("name") or "")
    author_url = oembed.get("author_url") or ""
    published = str((video or {}).get("uploadDate") or "")
    duration = str((video or {}).get("duration") or "")
    thumbnail = (oembed.get("thumbnail_url") or facts.og.get("og:image") or "")
    views = views_from_jsonld(entities)
    body = _text(html)
    loginish = any(w in body.lower() for w in (
        "log in", "sign in", "create an account", "enable javascript"))
    assessed = bool(title.strip())
    method = "oembed+html" if oembed.get("title") else "html_get"
    unavailable = [
        {"item": "Engagement rate / reach",
         "why": "Platform analytics; not published on the public page."},
        {"item": "Audience demographics",
         "why": "Private. Not inferred from comments or the thumbnail."},
    ]
    if views is None:
        unavailable.append({
            "item": "View / play count",
            "why": "Not present as JSON-LD interactionStatistic on this page.",
        })
    reason = ""
    if not assessed:
        reason = ("The URL returned no public title or VideoObject. "
                  "The page may be login-walled or blocked by robots.txt.")
    warnings = []
    if loginish and not oembed.get("title"):
        warnings.append("The HTML looks login-gated; metadata may be incomplete.")
    return MediaPayload(
        report_id="",
        generated_at=datetime.now(timezone.utc),
        url=url,
        platform=platform_of(url),
        title=str(title)[:300],
        description=str(description)[:800],
        author=str(author)[:160],
        author_url=str(author_url)[:300],
        published=published[:40],
        duration=duration[:40],
        thumbnail=str(thumbnail)[:400],
        view_count=views,
        word_count=facts.word_count,
        jsonld_types=facts.jsonld_types,
        method=method,
        assessed=assessed,
        reason=reason,
        unavailable=unavailable,
        warnings=warnings,
    )


async def analyse(url: str, report_id: str) -> MediaPayload:
    from app.engine.http import fetch

    api = bluesky_thread_url(url)
    if api:
        thread = await fetch(api)
        if thread.ok:
            try:
                data = json.loads(thread.text)
            except ValueError:
                data = None
            if isinstance(data, dict):
                payload = from_bluesky_thread(url, data)
                payload.report_id = report_id
                if payload.assessed:
                    return payload

    page = await fetch(url)
    if page.blocked_by_robots:
        raise RuntimeError("this URL is disallowed by robots.txt")
    if not page.ok:
        raise RuntimeError(f"fetch failed (status {page.status}"
                           f"{': ' + page.error if page.error else ''})")
    reddit_url = reddit_json_url(page.final_url or url)
    if reddit_url:
        listing = await fetch(reddit_url)
        if listing.ok:
            try:
                data = json.loads(listing.text)
            except ValueError:
                data = None
            if data is not None:
                payload = from_reddit_json(page.final_url or url, data)
                payload.report_id = report_id
                if payload.assessed:
                    return payload
    oembed = None
    oem_url = youtube_oembed_url(url) or tiktok_oembed_url(url)
    if oem_url:
        oem = await fetch(oem_url, check_robots=False)
        if oem.ok and oem.text.strip().startswith("{"):
            try:
                oembed = json.loads(oem.text)
            except ValueError:
                oembed = None
    payload = from_public_page(page.final_url or url, page.text, oembed=oembed)
    payload.report_id = report_id
    return payload


def video_id(url: str) -> str:
    parts = urlparse(url)
    if parts.netloc.lower() in {"youtu.be"}:
        return parts.path.strip("/")
    return (parse_qs(parts.query).get("v") or [""])[0]
