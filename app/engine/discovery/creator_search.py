"""Niche creator discovery for marketing-company workflows.

Modash-class entry point: search by topic/platform, return ranked candidate profiles
with public handles and enough context to open a diligence report. Requires a licensed
search provider; never scrapes SERP HTML.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

from app.config import settings
from app.engine.discovery.search import search
from app.omni.search_context import active_serper_key
from app.schemas import SearchHit

PLATFORM_PATTERNS = {
    "instagram": re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]{2,40})/?$", re.I),
    "youtube": re.compile(
        r"(?:https?://)?(?:www\.)?youtube\.com/(?:@([A-Za-z0-9._\-]{2,40})|channel/([A-Za-z0-9_\-]{10,}))/?",
        re.I,
    ),
    "tiktok": re.compile(r"(?:https?://)?(?:www\.)?tiktok\.com/@([A-Za-z0-9._]{2,40})/?", re.I),
    "linkedin": re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/([A-Za-z0-9\-_%]{2,80})/?", re.I),
    "x": re.compile(r"(?:https?://)?(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]{2,40})/?", re.I),
}

BLOCK = re.compile(
    r"(/p/|/reel/|/reels/|/explore|/tags?/|/accounts|/hashtag|/playlist|/watch|"
    r"/results|/shorts|/status/|/photo|/videos?/|/about|/posts?/)",
    re.I,
)

QUERY_TEMPLATES = [
    "top {q} creators {platform} india",
    "best {q} influencers {platform}",
    "{q} content creator {platform}",
    '"{q}" {platform} creator OR educator OR coach',
]


@dataclass
class CreatorHit:
    platform: str
    handle: str
    url: str
    title: str = ""
    snippet: str = ""
    score: float = 0.0
    sources: list[str] = field(default_factory=list)
    query: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DiscoveryResult:
    query: str
    platform: str
    assessed: bool
    reason: str = ""
    candidates: list[CreatorHit] = field(default_factory=list)
    queries_run: int = 0

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "platform": self.platform,
            "assessed": self.assessed,
            "reason": self.reason,
            "queries_run": self.queries_run,
            "candidates": [c.to_dict() for c in self.candidates],
        }


def _clean(url: str) -> str:
    return url.split("?")[0].split("#")[0].rstrip("/")


def _extract(url: str, platform_filter: str | None) -> tuple[str, str] | None:
    url = _clean(url)
    if BLOCK.search(url):
        return None
    for platform, pattern in PLATFORM_PATTERNS.items():
        if platform_filter and platform != platform_filter:
            continue
        m = pattern.search(url)
        if not m:
            continue
        handle = next((g for g in m.groups() if g), None)
        if not handle:
            continue
        handle = handle.strip(".")
        blocked = {"reel", "reels", "p", "explore", "stories", "tv", "share", "about"}
        if handle.lower() in blocked:
            continue
        if platform == "youtube" and handle.startswith("UC") and len(handle) > 20:
            canon = f"https://www.youtube.com/channel/{handle}"
        elif platform == "youtube":
            canon = f"https://www.youtube.com/@{handle}"
        elif platform == "instagram":
            canon = f"https://www.instagram.com/{handle}/"
        elif platform == "tiktok":
            canon = f"https://www.tiktok.com/@{handle}"
        elif platform == "linkedin":
            canon = f"https://www.linkedin.com/in/{handle}/"
        else:
            canon = f"https://x.com/{handle}"
        return platform, canon
    return None


def _handle_from_url(platform: str, url: str) -> str:
    path = urlparse(url).path.strip("/")
    if platform == "youtube" and path.startswith("@"):
        return path[1:]
    if platform == "youtube" and path.startswith("channel/"):
        return path.split("/", 1)[-1]
    if platform == "tiktok" and path.startswith("@"):
        return path[1:]
    return path.split("/")[0]


async def discover_creators(
    query: str,
    *,
    platform: str = "any",
    limit: int = 20,
) -> DiscoveryResult:
    """Rank public creator profile candidates for a niche query."""
    q = (query or "").strip()
    if len(q) < 2:
        return DiscoveryResult(query=q, platform=platform, assessed=False,
                               reason="Enter a niche, topic or keyword (at least 2 characters).")
    platform_filter = None if platform in ("", "any", "all") else platform.lower()
    plat_label = platform_filter or "instagram OR youtube"
    templates = QUERY_TEMPLATES if platform_filter != "tiktok" else [
        "top {q} creators tiktok",
        "{q} tiktok influencer",
        '"{q}" tiktok creator',
    ]
    hits: list[SearchHit] = []
    queries_run = 0
    for tmpl in templates[:3]:
        qq = tmpl.format(q=q, platform=plat_label)
        batch = await search(qq, limit=10)
        queries_run += 1
        for h in batch:
            h.query = qq
        hits.extend(batch)
        if len(hits) >= limit * 3:
            break

    if not hits:
        if settings.search_provider in ("", "none") and not (
            active_serper_key() or settings.brave_api_key or settings.google_cse_key
        ):
            return DiscoveryResult(
                query=q, platform=platform, assessed=False, queries_run=0,
                reason=("Creator discovery needs a licensed search key (serper.dev free tier works). "
                        "Add it in Settings — without it, paste a known creator URL on Workspace."),
            )
        return DiscoveryResult(
            query=q, platform=platform, assessed=True, queries_run=queries_run,
            reason="No public creator profiles matched this query. Try a narrower niche or another platform.",
        )

    ranked: dict[str, CreatorHit] = {}
    for hit in hits:
        extracted = _extract(hit.url, platform_filter)
        if not extracted:
            continue
        plat, canon = extracted
        handle = _handle_from_url(plat, canon)
        key = f"{plat}:{handle.lower()}"
        score = 12.0
        blob = f"{hit.title} {hit.snippet}".lower()
        ql = q.lower()
        if ql in blob:
            score += 25
        for token in re.findall(r"[a-z0-9]{3,}", ql):
            if token in blob:
                score += 6
        if any(w in blob for w in ("creator", "influencer", "youtuber", "educator",
                                   "coach", "official", "followers")):
            score += 8
        if hit.rank is not None:
            score += max(0, 12 - hit.rank)
        providers = list(hit.providers or ([hit.provider] if hit.provider else []))
        if key in ranked:
            existing = ranked[key]
            existing.score += score * 0.45
            for p in providers:
                if p and p not in existing.sources:
                    existing.sources.append(p)
            if len(hit.snippet or "") > len(existing.snippet or ""):
                existing.snippet = hit.snippet
            if len(hit.title or "") > len(existing.title or ""):
                existing.title = hit.title
        else:
            ranked[key] = CreatorHit(
                platform=plat, handle=handle, url=canon,
                title=(hit.title or "")[:140], snippet=(hit.snippet or "")[:220],
                score=score, sources=providers, query=hit.query or q,
            )

    candidates = sorted(ranked.values(), key=lambda c: (-c.score, c.platform, c.handle.lower()))
    for c in candidates:
        c.score = round(c.score, 1)
    return DiscoveryResult(
        query=q, platform=platform, assessed=True, queries_run=queries_run,
        candidates=candidates[:limit],
        reason="" if candidates else "Search returned pages, but none were clean creator profile URLs.",
    )
