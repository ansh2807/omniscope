"""Website Content DNA from crawled pages (spec §8), not a creator-performance model.

Hooks are homepage/sampled H1s. CTAs are phrases the pages themselves print.
There is no virality score here — that needs public post metrics.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ContentDNA(BaseModel):
    assessed: bool = False
    reason: str = ""
    hooks: list[str] = Field(default_factory=list)
    ctas: list[str] = Field(default_factory=list)
    language: str = ""
    pages_with_forms: int = 0
    pages_sampled: int = 0
    latest_dated: str | None = None
    methodology: str = (
        "Hooks = H1s on sampled pages. CTAs = matching phrases in page text. "
        "Language = html lang on the homepage. This is not engagement or "
        "hook-performance data.")


def from_pages(pages: list[Any]) -> ContentDNA:
    if not pages:
        return ContentDNA(assessed=False, reason="No pages were sampled.")
    hooks: list[str] = []
    seen: set[str] = set()
    ctas: list[str] = []
    cta_seen: set[str] = set()
    forms = 0
    for page in pages:
        for heading in getattr(page, "h1", []) or []:
            key = heading.strip().lower()
            if key and key not in seen:
                seen.add(key)
                hooks.append(heading.strip()[:120])
        for cta in getattr(page, "cta_hits", []) or []:
            key = cta.strip().lower()
            if key and key not in cta_seen:
                cta_seen.add(key)
                ctas.append(cta.strip().lower())
        if getattr(page, "forms", 0):
            forms += 1
    lang = getattr(pages[0], "lang", "") or ""
    dates = [d for p in pages for d in (getattr(p, "dates_seen", []) or [])]
    latest = sorted(dates)[-1] if dates else None
    return ContentDNA(
        assessed=True,
        hooks=hooks[:12],
        ctas=ctas[:12],
        language=lang[:16],
        pages_with_forms=forms,
        pages_sampled=len(pages),
        latest_dated=latest,
    )
