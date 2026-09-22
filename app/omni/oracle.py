"""ORACLE — predictive intelligence from observed snapshots only.

It compares this run to stored history and dated on-site content. It does not
forecast traffic, rankings, revenue or virality — those need data we do not have.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from pydantic import BaseModel, Field


class HistoryPoint(BaseModel):
    overall_score: float
    tech: list[str] = Field(default_factory=list)
    socials: list[str] = Field(default_factory=list)
    latest_dated_content: str | None = None
    observed_at: str = ""


class PredictionIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    direction: str = "unknown"       # rising | falling | stable | unknown
    score_delta: float | None = None
    previous_score: float | None = None
    observations: int = 1            # including the current run
    confidence: float = 0.0          # 0..1, printed; two points stay low
    freshness: str = "unknown"       # fresh | aging | stale | unknown
    days_since_dated_content: int | None = None
    tech_added: list[str] = Field(default_factory=list)
    tech_removed: list[str] = Field(default_factory=list)
    outlook: str = ""
    unavailable: list[str] = Field(default_factory=list)
    methodology: str = (
        "Direction is the difference between this run's website intelligence "
        "score and the previous stored snapshot. Confidence rises with the "
        "number of observations and stays low at n=2. Dated-content freshness "
        "uses timestamps the site itself published. Traffic, rankings and "
        "revenue are not forecast.")


UNAVAILABLE = [
    "Traffic or visitor forecasts — first-party analytics only.",
    "Search-ranking or demand trajectory — needs a rank-tracking provider.",
    "Revenue or conversion forecasts — private commercial data.",
    "Viral probability — not computable from a website crawl.",
]


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def forecast(*, current_score: float, current_tech: list[str],
             current_socials: list[str], latest_dated: str | None,
             history: list[HistoryPoint],
             today: date | None = None) -> PredictionIntel:
    """Pure function: current observation + prior snapshots → honest outlook."""
    today = today or datetime.now(timezone.utc).date()
    dated = _parse_day(latest_dated)
    days_old = (today - dated).days if dated else None
    if days_old is None:
        freshness = "unknown"
    elif days_old <= 90:
        freshness = "fresh"
    elif days_old <= 365:
        freshness = "aging"
    else:
        freshness = "stale"

    prev = history[-1] if history else None
    tech_added, tech_removed = [], []
    if prev:
        curr_set, prev_set = set(current_tech), set(prev.tech)
        tech_added = sorted(curr_set - prev_set)
        tech_removed = sorted(prev_set - curr_set)

    if not prev:
        outlook = (
            "First observation of this entity. A trajectory needs at least one "
            "prior run on the same domain.")
        if freshness == "stale":
            outlook += f" The newest dated page in the sample is {days_old} days old."
        elif freshness == "unknown":
            outlook += " No dated content was found on sampled pages."
        return PredictionIntel(
            assessed=False, reason=outlook, observations=1, freshness=freshness,
            days_since_dated_content=days_old, outlook=outlook,
            unavailable=list(UNAVAILABLE))

    delta = round(current_score - prev.overall_score, 1)
    if abs(delta) < 3:
        direction = "stable"
    elif delta > 0:
        direction = "rising"
    else:
        direction = "falling"
    n = len(history) + 1
    confidence = round(min(0.85, 0.35 + 0.12 * len(history)), 2)

    bits = [f"Score moved {delta:+.1f} vs the previous snapshot ({prev.overall_score:.1f} → {current_score:.1f})."]
    if abs(delta) < 3:
        bits.append("That is inside the ±3 noise band, so the direction is treated as stable.")
    if tech_added:
        bits.append("Newly observed technologies: " + ", ".join(tech_added) + ".")
    if tech_removed:
        bits.append("Technologies no longer observed: " + ", ".join(tech_removed) + ".")
    if freshness == "stale" and days_old is not None:
        bits.append(f"Newest dated content in the sample is {days_old} days old.")
    if n < 4:
        bits.append(f"Only {n} observations — treat this as a signal, not a forecast.")

    return PredictionIntel(
        assessed=True, direction=direction, score_delta=delta,
        previous_score=prev.overall_score, observations=n, confidence=confidence,
        freshness=freshness, days_since_dated_content=days_old,
        tech_added=tech_added, tech_removed=tech_removed,
        outlook=" ".join(bits), unavailable=list(UNAVAILABLE),
    )


def detect_changes(*, watched: bool, previous_score: float | None,
                   current_score: float, tech_added: list[str],
                   tech_removed: list[str],
                   socials_added: list[str],
                   socials_removed: list[str]) -> list[dict[str, str]]:
    """Alert drafts. Empty when the entity is not watched. Pure function."""
    if not watched:
        return []
    out: list[dict[str, str]] = []
    if previous_score is not None:
        delta = round(current_score - previous_score, 1)
        if abs(delta) >= 8:
            out.append({
                "kind": "score",
                "severity": "urgent" if abs(delta) >= 15 else "watch",
                "title": f"Intelligence score {delta:+.1f}",
                "detail": f"{previous_score:.1f} → {current_score:.1f} vs the last snapshot.",
            })
    if tech_added or tech_removed:
        parts = []
        if tech_added:
            parts.append("added " + ", ".join(tech_added))
        if tech_removed:
            parts.append("removed " + ", ".join(tech_removed))
        out.append({
            "kind": "tech", "severity": "info",
            "title": "Technology fingerprint changed",
            "detail": "; ".join(parts),
        })
    if socials_added or socials_removed:
        parts = []
        if socials_added:
            parts.append("new " + ", ".join(socials_added))
        if socials_removed:
            parts.append("gone " + ", ".join(socials_removed))
        out.append({
            "kind": "social", "severity": "info",
            "title": "Linked social accounts changed",
            "detail": "; ".join(parts),
        })
    return out
