"""Printed indexability directives (spec §17).

meta robots, googlebot and X-Robots-Tag are copied. A missing robots meta is
empty, not 'indexable'. These tokens are not a ranking, crawl-budget, or
Search Console claim.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.engine.collectors.web import _meta

RESTRICT = re.compile(
    r"\b(noindex|nofollow|nosnippet|noarchive|noimageindex|none|unavailable_after)\b",
    re.I)
AFTER = re.compile(r"unavailable_after\s*:?\s*(\d{4}-\d{2}-\d{2})", re.I)


class IndexRow(BaseModel):
    url: str
    source: str = "meta"
    raw: str = ""
    tokens: list[str] = Field(default_factory=list)
    unavailable_after: str = ""


class IndexIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    pages: list[IndexRow] = Field(default_factory=list)
    noindex: list[str] = Field(default_factory=list)
    nofollow: list[str] = Field(default_factory=list)
    methodology: str = (
        "Tokens are copied from meta robots / googlebot and X-Robots-Tag. "
        "Absence is empty, not a claim the page will rank. This is not "
        "Search Console or crawl-budget intelligence.")


def _tokens(*blobs: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for blob in blobs:
        for match in RESTRICT.finditer(blob or ""):
            token = match.group(1).lower()
            if token not in seen:
                seen.add(token)
                found.append(token)
    return found


def _after(*blobs: str) -> str:
    for blob in blobs:
        match = AFTER.search(blob or "")
        if match:
            return match.group(1)
    return ""


def tokens_from_page(html: str, headers: dict | None = None) -> list[str]:
    """Restrictive tokens on one page. Pure."""
    robots = _meta(html or "", "robots") or ""
    googlebot = _meta(html or "", "googlebot") or ""
    xrt = ""
    if headers:
        raw = {k.lower(): v for k, v in headers.items() if v}
        xrt = raw.get("x-robots-tag") or ""
    return _tokens(robots, googlebot, xrt)


def analyse_indexability(raw_html: list[tuple[str, str]],
                         headers: dict | None = None) -> IndexIntel:
    """Pure over already-fetched HTML plus optional homepage headers."""
    if not raw_html:
        return IndexIntel(assessed=False, reason="No pages were sampled.")
    pages: list[IndexRow] = []
    seen: set[tuple[str, str, str]] = set()
    for url, html in raw_html:
        robots = _meta(html or "", "robots") or ""
        googlebot = _meta(html or "", "googlebot") or ""
        raw = ", ".join(x for x in (robots, googlebot) if x)
        tokens = _tokens(robots, googlebot)
        after = _after(robots, googlebot)
        if not raw and not tokens:
            continue
        key = (url, "meta", raw.lower())
        if key in seen:
            continue
        seen.add(key)
        pages.append(IndexRow(
            url=url, source="meta", raw=raw[:160],
            tokens=tokens, unavailable_after=after))
    if headers:
        raw_h = {k.lower(): v for k, v in headers.items() if v}
        xrt = raw_h.get("x-robots-tag") or ""
        if xrt:
            home = raw_html[0][0]
            pages.append(IndexRow(
                url=home, source="header", raw=xrt[:160],
                tokens=_tokens(xrt), unavailable_after=_after(xrt)))
    noindex = []
    nofollow = []
    for row in pages:
        if "noindex" in row.tokens or "none" in row.tokens:
            if row.url not in noindex:
                noindex.append(row.url)
        if "nofollow" in row.tokens or "none" in row.tokens:
            if row.url not in nofollow:
                nofollow.append(row.url)
    if not pages:
        return IndexIntel(
            assessed=True,
            reason="No meta robots, googlebot or X-Robots-Tag on sampled pages.",
        )
    return IndexIntel(
        assessed=True,
        pages=pages[:20],
        noindex=noindex[:20],
        nofollow=nofollow[:20],
    )
