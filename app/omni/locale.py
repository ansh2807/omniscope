"""Printed locale tags from sampled pages (spec §11, §17).

html lang, og:locale, content-language and already-extracted hreflang are
copied. A language tag is not a market, a TAM, or proof of a country
operation. Missing lang is empty, not 'English-only'.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LocaleRow(BaseModel):
    url: str = ""
    lang: str = ""
    og_locale: str = ""


class LocaleIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    langs: list[str] = Field(default_factory=list)
    og_locales: list[str] = Field(default_factory=list)
    hreflang: list[str] = Field(default_factory=list)
    content_language: str = ""
    pages: list[LocaleRow] = Field(default_factory=list)
    methodology: str = (
        "Tags are copied from html lang, og:locale, the Content-Language header "
        "when recorded, and same-host hreflang. They are not demand, audience, "
        "or a country-presence score.")


def _norm(tag: str, *, limit: int = 16) -> str:
    return (tag or "").strip().replace("_", "-")[:limit]


def analyse_locale(pages: list[Any], *, hreflang: list[Any] | None = None,
                   content_language: str = "") -> LocaleIntel:
    """Pure over PageFacts-like rows plus optional printed alternates."""
    if not pages:
        return LocaleIntel(assessed=False, reason="No pages were sampled.")
    langs: list[str] = []
    og_locales: list[str] = []
    rows: list[LocaleRow] = []
    seen_lang: set[str] = set()
    seen_og: set[str] = set()
    for page in pages:
        lang = _norm(getattr(page, "lang", "") or "")
        og = {}
        raw_og = getattr(page, "og", None) or {}
        if isinstance(raw_og, dict):
            og = raw_og
        og_locale = _norm(str(og.get("og:locale") or ""))
        url = getattr(page, "url", "") or ""
        if lang or og_locale:
            rows.append(LocaleRow(url=url, lang=lang, og_locale=og_locale))
        if lang and lang.lower() not in seen_lang:
            seen_lang.add(lang.lower())
            langs.append(lang)
        if og_locale and og_locale.lower() not in seen_og:
            seen_og.add(og_locale.lower())
            og_locales.append(og_locale)
    alts: list[str] = []
    seen_alt: set[str] = set()
    for item in hreflang or []:
        tag = ""
        if isinstance(item, dict):
            tag = _norm(str(item.get("lang") or ""))
        else:
            tag = _norm(str(getattr(item, "lang", "") or ""))
        if tag and tag.lower() not in seen_alt:
            seen_alt.add(tag.lower())
            alts.append(tag)
    header = _norm(content_language, limit=40)
    if not langs and not og_locales and not alts and not header:
        return LocaleIntel(
            assessed=True,
            reason="No html lang, og:locale, hreflang or Content-Language on sampled pages.",
        )
    return LocaleIntel(
        assessed=True,
        langs=langs[:20],
        og_locales=og_locales[:20],
        hreflang=alts[:20],
        content_language=header,
        pages=rows[:20],
    )
