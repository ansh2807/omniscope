"""Company competitor discovery — search-led, evidence-backed, budget-aware.

A competitor is a distinct official website that ranks for "{name} alternatives"
or "{name} competitors". Directories, social platforms and the subject's own
domain are excluded. Without a search provider the engine says so; it does not
guess a rival list.
"""
from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.engine.discovery.search import search
from app.omni.keyless_web import duckduckgo_hits
from app.schemas import SearchHit

# Directories and platforms that rank for "X alternatives" but are not rivals.
NON_COMPETITOR_HOSTS = (
    "wikipedia.org", "linkedin.com", "facebook.com", "instagram.com", "youtube.com",
    "x.com", "twitter.com", "crunchbase.com", "glassdoor.", "indeed.", "amazon.",
    "flipkart.", "justdial.", "reddit.com", "quora.com", "medium.com", "github.com",
    "g2.com", "capterra.com", "trustradius.com", "producthunt.com", "getapp.com",
    "softwareadvice.com", "sourceforge.net", "trustpilot.com", "yelp.com",
    "play.google.com", "apps.apple.com", "tiktok.com",
)


class CompanyCompetitor(BaseModel):
    name: str
    url: str
    domain: str
    snippet: str = ""
    found_via: str = ""


class CompetitorIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    query_used: str = ""
    competitors: list[CompanyCompetitor] = Field(default_factory=list)
    methodology: str = (
        "Candidates come from a licensed search query for '{name} alternatives' "
        "(fallback: '{name} competitors'), or from DuckDuckGo Instant Answer "
        "related topics when no search key is present. Only distinct official "
        "websites are kept. Shared customers, market share and win/loss are not "
        "measured.")


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _is_directory(host: str) -> bool:
    return any(marker in host for marker in NON_COMPETITOR_HOSTS)


def pick_competitors(hits: list[SearchHit], self_domain: str, *,
                     limit: int = 5) -> list[CompanyCompetitor]:
    """Turn search hits into official-site rivals. Pure function."""
    self_host = self_domain.lower().removeprefix("www.")
    out: list[CompanyCompetitor] = []
    seen: set[str] = set()
    for hit in hits:
        host = _host(hit.url)
        if not host or host == self_host or host.endswith("." + self_host):
            continue
        if _is_directory(host) or host in seen:
            continue
        seen.add(host)
        title = (hit.title or host).strip()
        name = title.split(" - ")[0].split(" | ")[0].split(" – ")[0].strip()[:80] or host
        out.append(CompanyCompetitor(
            name=name, url=hit.url, domain=host,
            snippet=(hit.snippet or "")[:240],
            found_via=hit.query,
        ))
        if len(out) >= limit:
            break
    return out


async def discover(entity_name: str, domain: str) -> CompetitorIntel:
    """Search for company rivals. Falls back to DuckDuckGo Instant Answer."""
    name = (entity_name or domain).strip()
    query = f"{name} alternatives"
    source = "search"
    hits = await search(query, limit=10)
    if not hits:
        fallback = f"{name} competitors"
        hits = await search(fallback, limit=10)
        if hits:
            query = fallback
    if not hits:
        query = f"{name} alternatives"
        hits = await duckduckgo_hits(query, limit=10)
        source = "duckduckgo"
    if not hits:
        return CompetitorIntel(
            assessed=False,
            reason="Licensed search and DuckDuckGo Instant Answer both returned "
                   "no official-site rivals. Paste known competitor URLs as "
                   "separate investigations.",
            query_used=query,
        )
    rivals = pick_competitors(hits, domain)
    method = (
        "DuckDuckGo Instant Answer related topics for '{name} alternatives'. "
        "Published related entities only — not Google rankings, share, or win/loss."
        if source == "duckduckgo" else None
    )
    if not rivals:
        return CompetitorIntel(
            assessed=True,
            reason=f"Search for '{query}' returned only directories or the subject's "
                   "own properties. No distinct official website ranked as an alternative.",
            query_used=query,
            methodology=method or CompetitorIntel().methodology,
        )
    row = CompetitorIntel(assessed=True, query_used=query, competitors=rivals)
    if method:
        row.methodology = method
    return row
