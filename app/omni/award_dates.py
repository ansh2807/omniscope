"""Extract published dates from official award pages (spec §20).

Typical catalog seasons stay on AwardDef. This layer only records dates the
organizer's own page prints, with the surrounding words so a deadline is not
confused with a ceremony. No date → UNAVAILABLE, not last year's guess.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.engine.collectors.web import _text
from app.engine.http import fetch
from app.models import AwardFreshness
from app.omni.awards import CATALOG
from app.omni.documents import DATE_RE
from app.omni.events import emit

KIND_WORDS = (
    ("deadline", ("deadline", "entries close", "closing date", "submit by",
                  "applications close", "entry deadline")),
    ("opens", ("opens", "opening date", "entries open", "submissions open")),
    ("ceremony", ("ceremony", "awards night", "gala", "festival dates")),
    ("shortlist", ("shortlist", "finalists announced")),
)


class AwardDate(BaseModel):
    kind: str
    raw: str
    context: str
    source_url: str


class AwardDateIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    name: str = ""
    url: str = ""
    dates: list[AwardDate] = Field(default_factory=list)
    methodology: str = (
        "Dates are regex hits on the official award URL we fetched. Kind is "
        "the nearest keyword in an 80-character window. Typical catalog seasons "
        "are not copied onto these rows.")


def classify_window(window: str, *, date_at: int | None = None) -> str:
    """Nearest typed keyword wins. A later ceremony date must not inherit deadline."""
    blob = window.lower()
    anchor = date_at if date_at is not None else len(window) // 2
    best_kind = "mentioned"
    best_dist = 10**9
    for kind, words in KIND_WORDS:
        for word in words:
            start = 0
            while True:
                pos = blob.find(word, start)
                if pos < 0:
                    break
                dist = abs(pos - anchor)
                if dist < best_dist:
                    best_kind = kind
                    best_dist = dist
                start = pos + 1
    return best_kind


def extract_dates(html: str, url: str, *, name: str = "") -> AwardDateIntel:
    text = _text(html)
    if not text:
        return AwardDateIntel(
            assessed=False, name=name, url=url,
            reason="Official page had no extractable text.")
    found: list[AwardDate] = []
    for match in DATE_RE.finditer(text):
        start = max(0, match.start() - 80)
        end = min(len(text), match.end() + 80)
        raw_window = text[start:end]
        window = re.sub(r"\s+", " ", raw_window).strip()
        found.append(AwardDate(
            kind=classify_window(raw_window, date_at=match.start() - start),
            raw=match.group(0),
            context=window[:180],
            source_url=url,
        ))
    typed = [d for d in found if d.kind != "mentioned"]
    keep = (typed or found)[:8]
    if not keep:
        return AwardDateIntel(
            assessed=False, name=name, url=url,
            reason="No dates were printed on the official page we fetched.",
        )
    return AwardDateIntel(assessed=True, name=name, url=url, dates=keep)


def persist(session: Session, intel: AwardDateIntel, *, status: str) -> AwardFreshness:
    row = session.get(AwardFreshness, intel.name)
    if row is None:
        row = AwardFreshness(name=intel.name, url=intel.url)
    row.url = intel.url
    row.intel_json = intel.model_dump_json()
    row.fetched_at = datetime.utcnow()
    row.status = status
    session.add(row)
    session.commit()
    return row


def stored_map(session: Session) -> dict[str, AwardFreshness]:
    return {row.name: row for row in session.exec(select(AwardFreshness)).all()}


def intel_from_row(row: AwardFreshness) -> AwardDateIntel:
    if not row.intel_json:
        return AwardDateIntel(name=row.name, url=row.url, reason="No fetch stored.")
    try:
        data = json.loads(row.intel_json)
    except ValueError:
        return AwardDateIntel(name=row.name, url=row.url, reason="Stored date JSON was unreadable.")
    if not isinstance(data, dict):
        return AwardDateIntel(name=row.name, url=row.url, reason="Stored date JSON was unreadable.")
    return AwardDateIntel.model_validate(data)


def fetch_status(fetched) -> str:
    if getattr(fetched, "blocked_by_robots", False):
        return "robots"
    if getattr(fetched, "ok", False):
        return "ok"
    return "error"


async def refresh_catalog(session: Session) -> list[dict]:
    """Fetch each catalog URL through the compliant HTTP layer. No invented dates."""
    rows: list[dict] = []
    for award in CATALOG:
        fetched = await fetch(award.url)
        status = fetch_status(fetched)
        if status == "robots":
            intel = AwardDateIntel(
                assessed=False, name=award.name, url=award.url,
                reason="Official page blocked by robots.txt.")
        elif status == "error":
            reason = fetched.error or f"HTTP {fetched.status}" or "Fetch failed."
            intel = AwardDateIntel(
                assessed=False, name=award.name, url=award.url, reason=reason)
        else:
            intel = extract_dates(fetched.text, award.url, name=award.name)
            status = "assessed" if intel.assessed else "empty"
        persist(session, intel, status=status)
        rows.append({
            "name": award.name,
            "url": award.url,
            "status": status,
            "assessed": intel.assessed,
            "reason": intel.reason,
            "dates": [d.model_dump() for d in intel.dates],
        })
    emit("AWARD_DATES_REFRESHED", count=len(rows))
    return rows
