"""NARRATIVE RADAR — news/search clustering (spec §13).

Starts from licensed-search hits. Up to a few article URLs are then fetched
through the compliant HTTP layer for title, date and excerpt. Narrative labels
stay keyword matches. Circulation, sentiment scores and 'trending' are never
invented. No provider → assessed=False with an explicit reason.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.engine.collectors.web import _meta, _text
from app.engine.http import fetch
from app.omni.documents import DATE_RE
from app.omni.open_sources import HN_FALLBACK
from app.omni.open_sources import hacker_news
from app.schemas import SearchHit

SKIP_HOSTS = (
    "google.", "youtube.com", "youtu.be", "linkedin.com", "facebook.com",
    "instagram.com", "x.com", "twitter.com", "tiktok.com", "reddit.com",
    "g2.com", "capterra.com", "wikipedia.org", "news.ycombinator.com",
    "ycombinator.com",
)
HYDRATE_LIMIT = 4

NARRATIVES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("crisis", ("lawsuit", "sued", "recall", "breach", "outage", "scandal",
                "investigation", "fine", "layoff", "bankrupt")),
    ("criticism", ("criticized", "backlash", "complaint", "controversy",
                   "overpriced", "misleading")),
    ("product", ("launch", "released", "announces", "unveils", "update",
                 "feature", "version", "pricing")),
    ("leadership", ("ceo", "founder", "appoints", "resigns", "executive")),
    ("growth", ("funding", "raises", "acquisition", "expands", "partnership",
                "ipo", "valuation")),
)


class NewsItem(BaseModel):
    title: str
    url: str
    snippet: str = ""
    narrative: str = "other"
    source_query: str = ""
    source_host: str = ""
    published: str = ""
    excerpt: str = ""
    page_status: str = ""  # fetched | robots | error | skipped | ""


class ArticleFacts(BaseModel):
    title: str = ""
    published: str = ""
    excerpt: str = ""
    source_host: str = ""


class NewsIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    query_used: str = ""
    items: list[NewsItem] = Field(default_factory=list)
    narratives: dict[str, int] = Field(default_factory=dict)
    pages_hydrated: int = 0
    methodology: str = (
        "Items start as licensed-search hits. Up to four article URLs may be "
        "fetched for title, date and excerpt. Narrative labels are keyword "
        "matches on title+snippet+excerpt, not reach or a sentiment score.")


def classify_item(title: str, snippet: str) -> str:
    blob = f"{title} {snippet}".lower()
    for name, words in NARRATIVES:
        if any(re.search(rf"\b{re.escape(w)}\b", blob) for w in words):
            return name
    return "other"


def from_hits(hits: list[SearchHit], query: str) -> NewsIntel:
    """Cluster search hits. Pure function."""
    if not hits:
        return NewsIntel(
            assessed=False,
            reason="No news/search hits. Configure a search provider, or the "
                   "query returned nothing.",
            query_used=query,
        )
    items = [NewsItem(
        title=h.title or h.url, url=h.url, snippet=h.snippet or "",
        narrative=classify_item(h.title or "", h.snippet or ""),
        source_query=h.query or query,
        source_host=urlparse(h.url).netloc.lower().removeprefix("www."),
    ) for h in hits if h.url]
    return NewsIntel(assessed=True, query_used=query, items=items[:12],
                     narratives=_counts(items[:12]))


def _counts(items: list[NewsItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.narrative] = counts.get(item.narrative, 0) + 1
    return counts


def extract_article(url: str, html: str) -> ArticleFacts:
    """What the article page itself publishes. Pure function."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    title = (_meta(html, "og:title") or "").strip()
    if not title:
        match = re.search(r"<title[^>]*>([^<]+)", html, re.I)
        title = (match.group(1).strip() if match else "")
    published = (
        _meta(html, "article:published_time")
        or _meta(html, "og:published_time")
        or _meta(html, "datePublished")
        or ""
    ).strip()
    if not published:
        dates = DATE_RE.findall(_text(html)[:1200])
        published = dates[0] if dates else ""
    excerpt = (
        _meta(html, "og:description")
        or _meta(html, "description")
        or ""
    ).strip()
    if not excerpt:
        excerpt = re.sub(r"\s+", " ", _text(html))[:240].strip()
    return ArticleFacts(
        title=title[:300],
        published=str(published)[:40],
        excerpt=excerpt[:400],
        source_host=host,
    )


def apply_article(item: NewsItem, facts: ArticleFacts) -> NewsItem:
    """Merge fetched page facts. Does not invent a date or a narrative label."""
    if facts.title and (not item.title or item.title == item.url):
        item.title = facts.title
    if facts.published:
        item.published = facts.published
    if facts.excerpt:
        item.excerpt = facts.excerpt
    if facts.source_host:
        item.source_host = facts.source_host
    item.page_status = "fetched"
    item.narrative = classify_item(
        item.title, f"{item.snippet} {item.excerpt}")
    return item


def skip_host(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(token in host for token in SKIP_HOSTS)


async def hydrate(intel: NewsIntel, *, limit: int = HYDRATE_LIMIT) -> NewsIntel:
    """Fetch a few article pages. Robots/errors stay on the item; no backfill."""
    if not intel.assessed or not intel.items:
        return intel
    fetched = 0
    for item in intel.items:
        if fetched >= limit:
            break
        if skip_host(item.url):
            item.page_status = "skipped"
            continue
        page = await fetch(item.url)
        if page.blocked_by_robots:
            item.page_status = "robots"
            continue
        if not page.ok:
            item.page_status = "error"
            continue
        apply_article(item, extract_article(page.final_url or item.url, page.text))
        fetched += 1
    intel.pages_hydrated = fetched
    intel.narratives = _counts(intel.items)
    return intel


async def scan(entity_name: str, domain: str) -> NewsIntel:
    from app.omni.events import NEWS_DISCOVERED, emit
    from app.providers.search import search_provider

    query = f'"{entity_name}" {domain}'.strip()
    hits = await search_provider().get_news(query, limit=8)
    intel = from_hits(hits, query)
    if not intel.assessed:
        hn_hits = await hacker_news(entity_name, domain)
        intel = from_hits(hn_hits, query)
        if intel.assessed:
            intel.methodology = HN_FALLBACK
    if intel.assessed:
        intel = await hydrate(intel)
        emit(NEWS_DISCOVERED, entity=entity_name, n=len(intel.items),
             hydrated=intel.pages_hydrated)
    return intel
