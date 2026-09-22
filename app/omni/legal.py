"""Legal-page freshness from sampled policy URLs (spec §11, §34).

A privacy/terms/cookie/refund page is recorded only when it was in the crawl
sample. A homepage link we did not fetch is not a missing policy. Dates come
from time[datetime] or a printed date next to 'last updated' / 'effective'.
A footer year is not a revision date. Presence is not a compliance score.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from selectolax.parser import HTMLParser

from app.engine.collectors.web import _text
from app.omni.documents import DATE_RE
from app.omni.feeds import normalize_date

UPDATE_NEAR = re.compile(
    r"(last\s+updated|effective(?:\s+date)?|updated\s+on|revised(?:\s+on)?)",
    re.I)
POLICY_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("cookie", re.compile(r"/(cookie)s?(?:-policy)?(?:[/_.-]|$)", re.I)),
    ("refund", re.compile(
        r"/(refunds?|cancell?ation|return-policy|returns)(?:[/_.-]|$)", re.I)),
    ("privacy", re.compile(r"/(privacy)(?:-policy)?(?:[/_.-]|$)", re.I)),
    ("terms", re.compile(
        r"/(terms(?:-of-(?:service|use))?|tos)(?:[/_.-]|$)", re.I)),
    ("legal", re.compile(r"/legal/?$", re.I)),
)
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


class PolicyPage(BaseModel):
    kind: str
    url: str
    title: str = ""
    updated: str = ""


class LegalIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    policies: list[PolicyPage] = Field(default_factory=list)
    latest_updated: str | None = None
    methodology: str = (
        "Only sampled privacy/terms/cookie/refund URLs are read. Dates sit next "
        "to last-updated / effective wording or in time[datetime]. A copyright "
        "year is not a revision date. This is not a GDPR or DPDP score.")


def policy_kind(url: str) -> str | None:
    """Pure. None if this URL is not a policy path we record."""
    path = urlparse(url or "").path.lower()
    if not path or path in {"/", ""}:
        return None
    for kind, pat in POLICY_KINDS:
        if pat.search(path):
            return kind
    return None


def parse_printed_date(raw: str) -> str:
    """YYYY-MM-DD from a printed date. Empty if the string is not a date."""
    text = " ".join((raw or "").split())
    if not text:
        return ""
    iso = normalize_date(text)
    if iso:
        return iso
    match = re.match(
        r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", text)
    if match:
        return _ymd(match.group(3), match.group(1), match.group(2))
    match = re.match(
        r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})$", text)
    if match:
        return _ymd(match.group(3), match.group(2), match.group(1))
    return ""


def _ymd(year: str, month: str, day: str) -> str:
    month_n = MONTHS.get(month.lower())
    if not month_n:
        return ""
    try:
        return datetime(int(year), month_n, int(day)).date().isoformat()
    except ValueError:
        return ""


def extract_updated(html: str) -> str:
    """First revision date next to update wording. Pure over HTML."""
    if not html:
        return ""
    tree = HTMLParser(html)
    for node in tree.css("time[datetime]"):
        day = parse_printed_date(node.attributes.get("datetime") or "")
        parent = node.parent
        ctx = ""
        if parent is not None:
            ctx = parent.text(separator=" ", strip=True) or ""
        ctx = ctx or (node.text(strip=True) or "")
        if day and UPDATE_NEAR.search(ctx):
            return day
    text = _text(html)
    day_first = re.compile(
        r"\b(\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?),?\s+\d{4})\b", re.I)
    for match in list(DATE_RE.finditer(text)) + list(day_first.finditer(text)):
        start = max(0, match.start() - 70)
        window = text[start:match.end() + 16]
        if not UPDATE_NEAR.search(window):
            continue
        day = parse_printed_date(match.group(0))
        if day:
            return day
    return ""


def analyse_legal(raw_html: list[tuple[str, str]]) -> LegalIntel:
    """Pure over already-fetched pages."""
    policies: list[PolicyPage] = []
    seen: set[str] = set()
    for url, html in raw_html or []:
        kind = policy_kind(url)
        if not kind:
            continue
        clean = (url or "").split("#")[0].rstrip("/") or url
        if clean in seen:
            continue
        seen.add(clean)
        tree = HTMLParser(html or "")
        title_node = tree.css_first("title")
        title = title_node.text(strip=True)[:160] if title_node else ""
        policies.append(PolicyPage(
            kind=kind, url=clean, title=title,
            updated=extract_updated(html or "")))
    if not policies:
        return LegalIntel(
            assessed=False,
            reason="No privacy, terms, cookie or refund URL was in the sampled crawl.",
        )
    dated = sorted(p.updated for p in policies if p.updated)
    return LegalIntel(
        assessed=True,
        policies=policies[:12],
        latest_updated=dated[-1] if dated else None,
    )
