"""Locale-aware parsing for public social-media counters.

Platforms localise counters to the viewer.  On an Indian machine YouTube commonly
renders ``4.6 crore subscribers`` and ``8.5 lakh views`` instead of ``46M`` and
``850K``.  Treating the bare decimal as the full count silently corrupts every
downstream rate, ranking and audience estimate, so all collectors share this parser.
"""
from __future__ import annotations

import re

_COUNT = re.compile(
    r"(?<![\w.])([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
    r"(crores?|cr|lakhs?|lacs?|k|m|b|thousand|million|billion)?\b",
    re.I,
)

_MULTIPLIERS = {
    "": 1,
    "k": 1_000,
    "thousand": 1_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "lac": 100_000,
    "lacs": 100_000,
    "m": 1_000_000,
    "million": 1_000_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "cr": 10_000_000,
    "b": 1_000_000_000,
    "billion": 1_000_000_000,
}


def parse_human_count(text: str | None) -> int | None:
    """Return the first human-formatted count in *text*.

    Supports Western compact suffixes and Indian lakh/crore localisation.  The
    function is intentionally strict about the numeric token so it does not parse
    dates, handles or arbitrary prose as a count.
    """
    if not text:
        return None
    normalised = str(text).replace("\u00a0", " ").replace("\u202f", " ").strip()
    match = _COUNT.search(normalised)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    suffix = (match.group(2) or "").lower()
    return int(value * _MULTIPLIERS[suffix])
