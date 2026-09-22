"""Public comment collection.

YouTube comment threads are genuinely public and available through the official Data API
(`commentThreads.list`, 1 quota unit per call), so this is the one place the brief's
"analyse thousands of public comments" is actually achievable without touching a login
wall. We pull top-level comments for the highest-performing videos, which is where the
audience concentrates.

Instagram comments are login-walled and are NOT collected here. The report says so
rather than substituting YouTube comments and pretending they are the same audience.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from dateutil import parser as dateparser

from app.config import settings
from app.engine.http import fetch
from app.schemas import ContentItem

API = "https://www.googleapis.com/youtube/v3"


class Comment:
    __slots__ = ("text", "likes", "author", "published_at", "video_title", "video_url")

    def __init__(self, text: str, likes: int = 0, author: str | None = None,
                 published_at: datetime | None = None, video_title: str = "",
                 video_url: str | None = None):
        self.text = text
        self.likes = likes
        self.author = author
        self.published_at = published_at
        self.video_title = video_title
        self.video_url = video_url

    def __repr__(self) -> str:      # pragma: no cover
        return f"<Comment {self.likes}👍 {self.text[:48]!r}>"


def _vid(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"[?&]v=([A-Za-z0-9_\-]{6,})", url) or re.search(r"youtu\.be/([A-Za-z0-9_\-]{6,})", url)
    return m.group(1) if m else None


async def _via_browser(ranked: list[ContentItem]) -> tuple[list[Comment], list[str]]:
    """Read comment threads by rendering the watch page and scrolling — no API key.

    Comments are public: any visitor sees them without signing in. This tier reproduces
    that, which is what lets the sentiment section work on a machine with no API key.
    """
    from app.engine.collectors import browser as br
    if not br.enabled():
        return [], []
    urls = [c.url for c in ranked[:settings.browser_max_comment_videos] if c.url]
    if not urls:
        return [], []
    r = await br.youtube_comments(urls)
    if not r.ok:
        return [], ([r.error] if r.error else [])
    by_url = {c.url: c for c in ranked}
    out: list[Comment] = []
    for d in br.parse_comments(r.text):
        src = by_url.get(d.get("video_url"))
        out.append(Comment(text=d["text"], likes=d.get("likes", 0),
                           author=d.get("author"),
                           video_title=src.title if src else "",
                           video_url=d.get("video_url")))
    notes = list(r.notes)
    notes.append(f"{len(out)} public comments read by rendering the watch pages logged out. "
                 f"No API key was used and no account was signed into.")
    return out, notes


def _sample_has(item: ContentItem, label: str) -> bool:
    sample = item.raw.get("sample") or []
    if isinstance(sample, str):
        sample = [sample]
    return item.raw.get("sort") == label or label in sample


def _video_sample(content: list[ContentItem], max_videos: int) -> list[ContentItem]:
    """Balance major reach with current audience voice instead of sampling winners only."""
    viable = [c for c in content if c.platform == "youtube" and c.views and c.url]
    popular = sorted(viable, key=lambda c: c.views or 0, reverse=True)
    latest_tagged = [c for c in viable if _sample_has(c, "latest")]
    latest = sorted(latest_tagged or [c for c in viable if c.published_at],
                    key=lambda c: c.published_at or datetime.min, reverse=True)
    out, seen = [], set()
    for group in (popular[:max(1, max_videos // 2)], latest):
        for item in group:
            key = _vid(item.url) or item.url
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
            if len(out) >= max_videos:
                return out
    return out


async def collect_youtube(content: list[ContentItem], *, max_videos: int = 16,
                          per_video: int = 200) -> tuple[list[Comment], list[str]]:
    """Top-level comments from a reach-and-recency video sample. Returns comments and notes.

    Two tiers: the official Data API when a key is configured, otherwise a rendered
    browser reading the same public threads a visitor sees.
    """
    notes: list[str] = []
    ranked_all = _video_sample(content, max_videos)

    if not settings.youtube_api_key:
        got, bnotes = await _via_browser(ranked_all)
        notes.extend(bnotes)
        if got:
            return got, notes
        from app.engine.collectors import browser as br
        notes.append(
            "Comment collection needs either a YouTube Data API key or the browser tier. "
            + (br.INSTALL_HINT if not br.available() else
               "The browser tier was enabled but returned no comments — the videos may "
               "have comments disabled.")
            + " Sentiment is therefore built only from verbatim review text the creator "
              "publishes themselves, if any."
        )
        return [], notes

    ranked = [c for c in ranked_all if _vid(c.url)]
    if not ranked:
        notes.append("No YouTube videos with resolvable IDs were available for comment collection.")
        return [], notes

    out: list[Comment] = []
    disabled = 0
    # Relevance-ranked comments surface the most endorsed discussion; time-ranked comments
    # capture current questions. The union reduces (but cannot eliminate) ranking bias.
    orders = ["relevance", "time"] if per_video > 100 else ["relevance"]
    per_order = min(100, max(1, (per_video + len(orders) - 1) // len(orders)))
    seen_comments: set[tuple[str, str, str]] = set()
    for item in ranked:
        vid = _vid(item.url)
        video_disabled = False
        for order in orders:
            url = (f"{API}/commentThreads?part=snippet&videoId={vid}"
                   f"&maxResults={per_order}&order={order}"
                   f"&textFormat=plainText&key={settings.youtube_api_key}")
            r = await fetch(url, check_robots=False)
            if not r.ok:
                if r.status == 403:
                    video_disabled = True
                continue
            try:
                data = json.loads(r.text)
            except json.JSONDecodeError:
                continue
            for th in data.get("items", []):
                sn = (th.get("snippet", {}).get("topLevelComment", {}) or {}).get("snippet", {})
                text = (sn.get("textOriginal") or "").strip()
                if not text:
                    continue
                author = sn.get("authorDisplayName")
                dedupe_key = (item.url or "", (author or "").strip().lower(),
                              re.sub(r"\s+", " ", text.lower()).strip())
                if dedupe_key in seen_comments:
                    continue
                seen_comments.add(dedupe_key)
                try:
                    pub = dateparser.parse(sn.get("publishedAt")) if sn.get("publishedAt") else None
                except Exception:
                    pub = None
                out.append(Comment(
                    text=text, likes=int(sn.get("likeCount") or 0),
                    author=author, published_at=pub,
                    video_title=item.title, video_url=item.url,
                ))
        if video_disabled:
            disabled += 1

    if disabled:
        notes.append(f"{disabled} of {len(ranked)} videos had comments disabled or restricted.")
    if not out:
        got, bnotes = await _via_browser(ranked_all)
        notes.extend(bnotes)
        if got:
            return got, notes
    notes.append(
        f"{len(out)} deduplicated public top-level comments collected across {len(ranked)} "
        f"videos via the YouTube Data API, balancing high-view and recent videos and combining "
        f"{', '.join(orders)}-ranked threads."
    )
    return out, notes
