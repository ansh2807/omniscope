"""Risk analyst from observed news narratives (spec §27 / §31).

Severity is a count of crisis/criticism labels already assigned to search hits.
It is not a probability of harm and not a credit or legal score.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RiskIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    level: str = "none"          # none | watch | elevated
    crisis_n: int = 0
    criticism_n: int = 0
    items: list[dict] = Field(default_factory=list)
    methodology: str = (
        "Level is derived from keyword narrative labels on licensed-search "
        "snippets. ELEVATED = 2+ crisis items. WATCH = any crisis or 2+ "
        "criticism items. This is not incident confirmation.")


def from_news(news_intel: dict | None) -> RiskIntel:
    intel = news_intel or {}
    if not intel.get("assessed"):
        return RiskIntel(
            assessed=False,
            reason=intel.get("reason") or "News radar was not assessed.",
        )
    items = []
    crisis = criticism = 0
    for raw in intel.get("items") or []:
        label = raw.get("narrative") or "other"
        if label == "crisis":
            crisis += 1
            items.append(raw)
        elif label == "criticism":
            criticism += 1
            items.append(raw)
    if crisis >= 2:
        level = "elevated"
    elif crisis >= 1 or criticism >= 2:
        level = "watch"
    else:
        level = "none"
    return RiskIntel(
        assessed=True,
        level=level,
        crisis_n=crisis,
        criticism_n=criticism,
        items=items[:8],
    )
