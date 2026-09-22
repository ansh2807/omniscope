"""Award intelligence — catalog matcher over what the site (and optional search) say.

The catalog is a known-list matcher, not a claim that every award on earth was
discovered. Seasons are typical, not this year's official deadline. A win is
``self_claimed`` when the subject's own pages say so; it is never upgraded to
verified without a third-party source we actually fetched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.engine.collectors.web import _text

CLAIM_RE = re.compile(
    r"\b(won|winner|awarded|recipient|took home|shortlist(?:ed)?|finalist|"
    r"nominated|gold|silver|bronze)\b", re.I)
GENERIC_RE = re.compile(
    r"\b(award[- ]winning|award[- ]winningly|industry awards?|best .+ award)\b", re.I)


@dataclass(frozen=True)
class AwardDef:
    name: str
    aliases: tuple[str, ...]
    org: str
    season: str
    region: str
    category: str
    url: str


# Curated, well-known marketing/creative/product awards. Typical season only.
CATALOG: tuple[AwardDef, ...] = (
    AwardDef("Cannes Lions", ("cannes lions", "cannes lion"), "Cannes Lions",
             "June", "global", "creative", "https://www.canneslions.com/"),
    AwardDef("Clio Awards", ("clio awards", "clio award"), "Clios",
             "Spring", "global", "creative", "https://clios.com/"),
    AwardDef("D&AD", ("d&ad", "d and ad"), "D&AD",
             "Spring", "global", "creative", "https://www.dandad.org/"),
    AwardDef("The One Show", ("the one show", "one show pencil"), "The One Club",
             "Spring", "global", "creative", "https://www.oneshow.org/"),
    AwardDef("Effie Awards", ("effie awards", "effie award"), "Effie Worldwide",
             "Year-round / regional", "global", "marketing", "https://www.effie.org/"),
    AwardDef("Webby Awards", ("webby awards", "webby award", "the webbys"), "IADAS",
             "Spring", "global", "digital", "https://www.webbyawards.com/"),
    AwardDef("Shorty Awards", ("shorty awards", "shorty award"), "Shorty Awards",
             "Spring", "global", "digital", "https://shortyawards.com/"),
    AwardDef("The Stevie Awards", ("stevie awards", "stevie award"), "Stevie Awards",
             "Year-round", "global", "business", "https://stevieawards.com/"),
    AwardDef("Abby Awards", ("abby awards", "abby award"), "The Advertising Club",
             "India cycle", "india", "creative", "https://www.theadvertisingclub.net/"),
    AwardDef("EMVIES", ("emvies", "emvie award"), "The Advertising Club",
             "India cycle", "india", "media", "https://www.theadvertisingclub.net/"),
    AwardDef("Foxglove Awards", ("foxglove awards", "foxglove award"), "afaqs!",
             "India cycle", "india", "digital", "https://www.afaqs.com/"),
)


class AwardMention(BaseModel):
    award: str
    status: str              # mentioned | self_claimed
    source_url: str
    excerpt: str
    catalog_url: str = ""


class AwardCalendarEntry(BaseModel):
    name: str
    org: str
    season: str
    region: str
    category: str
    url: str
    mentioned_on_site: bool = False


class AwardIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    mentions: list[AwardMention] = Field(default_factory=list)
    generic_claims: list[str] = Field(default_factory=list)
    calendar: list[AwardCalendarEntry] = Field(default_factory=list)
    methodology: str = (
        "On-site mentions are matched against a curated catalog of well-known "
        "marketing, creative and digital awards. Seasons are typical, not fetched "
        "deadlines. A win stated only on the subject's own pages is self-claimed.")


def _excerpt(text: str, needle: str, radius: int = 90) -> str:
    i = text.lower().find(needle.lower())
    if i < 0:
        return ""
    start, end = max(0, i - radius), min(len(text), i + len(needle) + radius)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def analyse_awards(pages: list[tuple[str, str]]) -> AwardIntel:
    """Scan fetched HTML for catalog awards and generic award language. Pure."""
    mentions: list[AwardMention] = []
    generic: list[str] = []
    mentioned_names: set[str] = set()

    for url, html in pages:
        text = _text(html)
        if not text:
            continue
        lower = text.lower()
        if GENERIC_RE.search(text):
            generic.append(_excerpt(text, GENERIC_RE.search(text).group(0))[:220])
        for award in CATALOG:
            hit = next((a for a in award.aliases if a in lower), None)
            if not hit:
                continue
            excerpt = _excerpt(text, hit)
            window = lower[max(0, lower.find(hit) - 120):lower.find(hit) + 160]
            status = "self_claimed" if CLAIM_RE.search(window) else "mentioned"
            mentions.append(AwardMention(
                award=award.name, status=status, source_url=url,
                excerpt=excerpt, catalog_url=award.url))
            mentioned_names.add(award.name)

    # One row per award (prefer self_claimed over a bare mention).
    by_name: dict[str, AwardMention] = {}
    for m in mentions:
        prev = by_name.get(m.award)
        if prev is None or (m.status == "self_claimed" and prev.status != "self_claimed"):
            by_name[m.award] = m

    calendar = [
        AwardCalendarEntry(
            name=a.name, org=a.org, season=a.season, region=a.region,
            category=a.category, url=a.url,
            mentioned_on_site=a.name in mentioned_names)
        for a in CATALOG
    ]

    if not by_name and not generic:
        return AwardIntel(
            assessed=True,
            reason="No curated award names or generic award language were found on "
                   "the sampled pages. This is not evidence the entity has never "
                   "won anything — only that these pages do not say so.",
            calendar=calendar,
        )
    return AwardIntel(
        assessed=True,
        mentions=list(by_name.values()),
        generic_claims=list(dict.fromkeys(generic))[:6],
        calendar=calendar,
    )
