"""SIGNAL — trend classes from observed snapshot series (spec §19).

Classes describe this entity's measured score trajectory, not the open web.
Volume, hashtag velocity and search demand stay UNAVAILABLE.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.omni.oracle import HistoryPoint

CLASSES = ("emerging", "accelerating", "peak", "stable", "declining", "insufficient")


class TrendIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    classification: str = "insufficient"
    velocity: float | None = None      # points per observation
    persistence: int = 1               # how many snapshots exist
    methodology: str = (
        "Classification uses the stored website-intelligence score series for "
        "this entity. EMERGING = first rise from a single prior point. "
        "ACCELERATING = rise continuing. PEAK = rise then flat/down. "
        "STABLE = |delta| < 3. DECLINING = falling. This is not search-trend "
        "or social-volume data.")


def classify_series(scores: list[float]) -> TrendIntel:
    """Pure function over a score series (oldest → newest, including current)."""
    if len(scores) < 2:
        return TrendIntel(
            assessed=False,
            classification="insufficient",
            persistence=len(scores),
            reason="Need at least two stored observations to classify a trend.",
        )
    latest, prev = scores[-1], scores[-2]
    delta = latest - prev
    velocity = round(delta, 2)
    if len(scores) >= 3:
        earlier = scores[-3]
        prev_delta = prev - earlier
    else:
        prev_delta = None

    if abs(delta) < 3:
        if prev_delta is not None and prev_delta >= 5:
            klass = "peak"
        else:
            klass = "stable"
    elif delta >= 5 and prev_delta is not None and prev_delta >= 5:
        klass = "accelerating"
    elif delta >= 3 and prev_delta is None:
        klass = "emerging"
    elif delta >= 3:
        klass = "accelerating"
    else:
        klass = "declining"

    return TrendIntel(
        assessed=True,
        classification=klass,
        velocity=velocity,
        persistence=len(scores),
    )


def from_history(current_score: float, history: list[HistoryPoint]) -> TrendIntel:
    series = [h.overall_score for h in history] + [current_score]
    return classify_series(series)
