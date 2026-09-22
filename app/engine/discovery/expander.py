"""Identity expansion: seed URL -> every public surface this person owns.

Two independent evidence streams, cross-referenced:
  A. Owned-link graph  — follow the creator's own outbound links (bio link, link-in-bio
     page, website footer). Highest trust: they published it themselves.
  B. Search/dork layer — run operator templates through a licensed search API and keep
     hits whose URL handle or page title matches the seed identity.

A hit needs either stream to be recorded, but only stream A (or a strong name+handle
match in stream B) promotes a URL to "collect this too".
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.config import settings
from app.engine.collectors.github import username_from as github_username
from app.engine.collectors.hackernews import username_from as hackernews_username
from app.engine.collectors.mastodon import NOT_MASTODON
from app.engine.collectors.pinterest import username_from as pinterest_username
from app.engine.collectors.soundcloud import username_from as soundcloud_username
from app.engine.discovery import dorks as dork_lib
from app.engine.discovery.search import search
from app.engine.resolver import resolve
from app.schemas import SearchHit

SOCIAL_HOSTS = {
    "instagram.com": "instagram", "youtube.com": "youtube", "youtu.be": "youtube",
    "linkedin.com": "linkedin", "x.com": "x", "twitter.com": "x",
    "threads.net": "threads", "threads.com": "threads", "facebook.com": "facebook",
    "tiktok.com": "tiktok", "reddit.com": "reddit",
    "bsky.app": "bluesky",
    "mastodon.social": "mastodon",
    "mastodon.online": "mastodon",
    "fb.com": "facebook", "t.me": "telegram", "telegram.me": "telegram",
    "topmate.io": "topmate", "superprofile.bio": "superprofile", "linktr.ee": "linktree",
    "beacons.ai": "linktree", "bio.link": "linktree",
    "apps.apple.com": "appstore", "play.google.com": "playstore",
    "open.spotify.com": "podcast", "podcasts.apple.com": "podcast",
    "substack.com": "website", "medium.com": "website",
}

JUNK = re.compile(
    r"(privacy|terms|cookie|/help|/about$|/legal|support\.|policies|/careers|"
    r"wikipedia\.org|google\.com/(?!store)|bit\.ly/?$)", re.I)


@dataclass
class Expansion:
    display_name: str | None = None
    targets: list[tuple[str, str]] = field(default_factory=list)  # (platform, url)
    sources: dict[str, str] = field(default_factory=dict)         # url -> how we found it
    probe_confidence: dict[str, float] = field(default_factory=dict)
    search_hits: list[SearchHit] = field(default_factory=list)
    discovered: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_target(self, platform: str, url: str, *, source: str = "search",
                   confidence: float = 0.0) -> None:
        keep_query = platform in ("playstore", "hackernews")
        clean = url if keep_query else url.split("?")[0]
        clean = clean.rstrip("/") + ("/" if platform == "instagram" else "")
        if not any(u == clean for _, u in self.targets):
            self.targets.append((platform, clean))
        # Strongest provenance wins if the same URL arrives twice.
        rank = {"seed": 4, "owned_link": 3, "probe": 2, "wikidata": 2, "search": 1}
        if rank.get(source, 0) >= rank.get(self.sources.get(clean, ""), 0):
            self.sources[clean] = source
            if confidence:
                self.probe_confidence[clean] = confidence


def classify(url: str) -> str | None:
    parts = urlparse(url)
    host = parts.netloc.lower().replace("www.", "")
    path = (parts.path or "").lower()
    if host.endswith("spotify.com"):
        return "website" if "/artist/" in path else "podcast"
    if host == "github.com":
        return "github" if github_username(url) else "website"
    if host == "soundcloud.com":
        return "soundcloud" if soundcloud_username(url) else "website"
    if host == "pinterest.com" or host.startswith("pinterest."):
        return "pinterest" if pinterest_username(url) else "website"
    if host == "news.ycombinator.com":
        return "hackernews" if hackernews_username(url) else "website"
    for h, platform in SOCIAL_HOSTS.items():
        if host == h or host.endswith("." + h):
            return platform
    if re.match(r"^/@[A-Za-z0-9_\.]{1,30}/?$", path):
        if host not in NOT_MASTODON and not any(
                host.endswith("." + item) for item in NOT_MASTODON):
            return "mastodon"
    return "website" if host else None


def _handle_of(url: str) -> str:
    try:
        return resolve(url).handle.lower()
    except Exception:
        return ""


def _name_tokens(name: str) -> set[str]:
    generic = {"official", "creator", "educator", "mentor", "coach", "founder",
               "speaker", "channel", "profile", "india", "website"}
    return {t for t in re.split(r"[^a-z0-9]+", (name or "").lower())
            if len(t) > 2 and t not in generic}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _identity_score(hit: SearchHit, *, name: str, handle: str,
                    dork: dork_lib.Dork) -> float:
    """Score identity evidence without allowing popularity or rank to prove ownership."""
    title_blob = f"{hit.title} {hit.snippet}".lower()
    url_handle = _handle_of(hit.url)
    name_tokens = _name_tokens(name)
    page_tokens = _name_tokens(title_blob)
    overlap = len(name_tokens & page_tokens) / max(1, len(name_tokens))
    exact_handle = bool(handle and _norm(handle) == _norm(url_handle))
    handle_mentioned = bool(handle and _norm(handle) in _norm(title_blob))
    exact_name = bool(name and _norm(name) and _norm(name) in _norm(title_blob))

    score = 0.08
    score += 0.48 if exact_handle else 0.0
    score += 0.20 if handle_mentioned else 0.0
    score += 0.32 if exact_name else 0.0
    score += min(0.24, overlap * 0.24)
    score += min(0.12, 0.06 * max(0, len(hit.providers) - 1))
    score += 0.05 if dork in dork_lib.PLATFORM_DORKS else 0.0
    score += 0.04 if (hit.rank or 99) <= 3 else 0.0
    if url_handle and handle and not exact_handle and not handle_mentioned:
        # A full-name match can still be a namesake. Different handles therefore
        # require an owned link, cross-link or later collected-page corroboration.
        score -= 0.28
    return round(max(0.0, min(1.0, score * dork.weight)), 3)


def _merge_hits(hits: list[SearchHit]) -> list[SearchHit]:
    """Deduplicate search evidence while retaining every query/provider provenance."""
    grouped: dict[str, list[SearchHit]] = {}
    for hit in hits:
        key = hit.url.rstrip("/").lower()
        grouped.setdefault(key, []).append(hit)
    out: list[SearchHit] = []
    for rows in grouped.values():
        rows.sort(key=lambda h: (-(h.identity_score or 0.0), h.rank or 999))
        best = rows[0]
        providers = list(dict.fromkeys(p for r in rows for p in r.providers))
        query_ids = list(dict.fromkeys(r.query_id for r in rows if r.query_id))
        purposes = list(dict.fromkeys(r.purpose for r in rows if r.purpose))
        longest = max(rows, key=lambda h: len(h.snippet or ""))
        out.append(best.model_copy(update={
            "providers": providers,
            "provider": "+".join(providers),
            "matched_queries": query_ids,
            "purposes": purposes,
            "snippet": longest.snippet,
            "rank": min((r.rank or 999) for r in rows),
            "identity_score": max((r.identity_score or 0.0) for r in rows),
        }))
    out.sort(key=lambda h: (-(h.identity_score or 0.0), -len(h.providers), h.rank or 999))
    return out


async def expand(
    seed_platform: str,
    seed_handle: str,
    seed_url: str,
    *,
    display_name: str | None = None,
    owned_links: list[str] | None = None,
    run_dorks: bool = True,
) -> Expansion:
    exp = Expansion(display_name=display_name)
    exp.add_target(seed_platform, seed_url, source="seed")

    # ---- stream A: links the creator published themselves -------------------
    for link in owned_links or []:
        if JUNK.search(link):
            continue
        platform = classify(link)
        if not platform:
            continue
        exp.discovered.append(link)
        exp.add_target(platform, link, source="owned_link")

    # ---- stream B: search operators ----------------------------------------
    if not run_dorks:
        return exp

    name = display_name or seed_handle
    queries = dork_lib.build(dork_lib.ALL_DORKS, name=name, handle=seed_handle)
    queries = queries[:max(1, settings.discovery_query_budget)]
    if not queries:
        return exp

    probe = await search(queries[0][1], limit=3)
    if not probe:
        exp.warnings.append(
            "Search provider not configured or returned nothing — identity expansion ran on "
            "owned links only. Set SEARCH_PROVIDER and a key to enable the dork layer."
        )
        return exp
    sem = asyncio.Semaphore(max(1, settings.discovery_concurrency))

    async def run_query(dork: dork_lib.Dork, q: str) -> tuple[dork_lib.Dork, list[SearchHit]]:
        async with sem:
            rows = await search(q, limit=6)
        return dork, [h.model_copy(update={
            "query_id": dork.id,
            "purpose": dork.purpose,
            "matched_queries": [dork.id],
            "purposes": [dork.purpose],
            "identity_score": _identity_score(h, name=name, handle=seed_handle, dork=dork),
        }) for h in rows]

    batches = [(queries[0][0], [h.model_copy(update={
        "query_id": queries[0][0].id,
        "purpose": queries[0][0].purpose,
        "matched_queries": [queries[0][0].id],
        "purposes": [queries[0][0].purpose],
        "identity_score": _identity_score(h, name=name, handle=seed_handle,
                                            dork=queries[0][0]),
    }) for h in probe])]
    batches += list(await asyncio.gather(*(run_query(d, q) for d, q in queries[1:])))
    exp.search_hits = _merge_hits([h for _, hits in batches for h in hits])

    for dork, hits in batches:
        if dork not in dork_lib.PLATFORM_DORKS:
            continue
        for h in hits:
            if JUNK.search(h.url):
                continue
            platform = classify(h.url)
            if not platform or platform == "website":
                continue
            score = h.identity_score or 0.0
            if score >= 0.68 and dork.weight >= 0.7:
                exp.discovered.append(h.url)
                exp.add_target(platform, h.url, source="search", confidence=score)

    return exp
