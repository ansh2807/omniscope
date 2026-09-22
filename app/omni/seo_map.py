"""SEO coverage map (spec §17) — on-page inventory, not a keyword-demand map.

Demand and SERP competition are unavailable without a rank/keyword provider.
This engine reports which expected commercial surfaces exist, are thin, or
are missing from the crawl sample and sitemap.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field

SLOTS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("pricing", "HIGH commercial intent", re.compile(r"/(pricing|plans)(?:[/_.-]|$)", re.I)),
    ("about", "brand / trust", re.compile(r"/(about|company|story)(?:[/_.-]|$)", re.I)),
    ("blog", "content / demand capture", re.compile(r"/(blog|news|articles|insights)(?:[/_.-]|$)", re.I)),
    ("docs", "product education", re.compile(r"/(docs|documentation|help|support)(?:[/_.-]|$)", re.I)),
    ("careers", "employer brand", re.compile(r"/(careers|jobs|hiring)(?:[/_.-]|$)", re.I)),
    ("contact", "conversion", re.compile(r"/(contact|demo|talk)(?:[/_.-]|$)", re.I)),
    ("legal", "trust", re.compile(r"/(privacy|terms|legal)(?:[/_.-]|$)", re.I)),
)

THIN_WORDS = 120


class CoverageSlot(BaseModel):
    slot: str
    intent: str
    status: str          # present | thin | missing
    url: str = ""
    word_count: int = 0
    evidence: str = ""


class SeoMap(BaseModel):
    assessed: bool = True
    reason: str = ""
    slots: list[CoverageSlot] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    canonical_conflicts: list[str] = Field(default_factory=list)
    methodology: str = (
        "A coverage map of expected commercial paths against the crawl sample "
        "and sitemap URLs. Quadrants are PRESENT / THIN / MISSING — not "
        "HIGH-DEMAND × LOW-COMPETITION. Keyword demand is unavailable.")


def coverage_map(pages: list[Any], sitemap_urls: list[str] | None = None) -> SeoMap:
    """Pure function. `pages` are PageFacts-like (url, word_count, h1, title)."""
    sitemap_urls = sitemap_urls or []
    inventory = list(pages)
    paths = [getattr(p, "url", "") for p in inventory] + list(sitemap_urls)
    slots: list[CoverageSlot] = []
    for name, intent, pat in SLOTS:
        matched_page = next(
            (p for p in inventory if pat.search(getattr(p, "url", "") or "")), None)
        in_sitemap = next((u for u in sitemap_urls if pat.search(u)), "")
        if matched_page is not None:
            words = int(getattr(matched_page, "word_count", 0) or 0)
            status = "thin" if words and words < THIN_WORDS else "present"
            if not words:
                status = "present"
            slots.append(CoverageSlot(
                slot=name, intent=intent, status=status,
                url=getattr(matched_page, "url", ""),
                word_count=words,
                evidence=f"sampled page, {words} words"))
        elif in_sitemap:
            slots.append(CoverageSlot(
                slot=name, intent=intent, status="present",
                url=in_sitemap, evidence="listed in sitemap; page not sampled"))
        else:
            slots.append(CoverageSlot(
                slot=name, intent=intent, status="missing",
                evidence="not in sampled pages or sitemap URLs"))
    topics: list[str] = []
    seen: set[str] = set()
    for page in inventory:
        for heading in list(getattr(page, "h1", []) or [])[:2]:
            key = heading.strip().lower()
            if key and key not in seen:
                seen.add(key)
                topics.append(heading.strip()[:80])
        title = (getattr(page, "title", "") or "").strip()
        if title and title.lower() not in seen:
            seen.add(title.lower())
            topics.append(title[:80])
    conflicts: list[str] = []
    for page in inventory:
        url = getattr(page, "url", "") or ""
        canon = getattr(page, "canonical", "") or ""
        if not url or not canon:
            continue
        fetched_host = urlparse(url).netloc.lower().removeprefix("www.")
        canon_abs = urljoin(url, canon)
        canon_host = urlparse(canon_abs).netloc.lower().removeprefix("www.")
        if canon_host and fetched_host and canon_host != fetched_host:
            conflicts.append(f"{url} canonical→ {canon_abs}")
    return SeoMap(slots=slots, topics=topics[:12],
                  canonical_conflicts=conflicts[:8])
