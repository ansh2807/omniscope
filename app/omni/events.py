"""In-process intelligence events (spec §36).

A queue/broker can subscribe later without engines changing — they only call
``emit``. Handlers stay optional; the default handler is structured logging.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("omniscope.events")

ENTITY_DISCOVERED = "ENTITY_DISCOVERED"
URL_DISCOVERED = "URL_DISCOVERED"
CRAWL_STARTED = "CRAWL_STARTED"
CRAWL_COMPLETED = "CRAWL_COMPLETED"
ENTITY_RESOLVED = "ENTITY_RESOLVED"
EVIDENCE_ADDED = "EVIDENCE_ADDED"
ANALYSIS_STARTED = "ANALYSIS_STARTED"
ANALYSIS_COMPLETED = "ANALYSIS_COMPLETED"
NEWS_DISCOVERED = "NEWS_DISCOVERED"
TREND_DETECTED = "TREND_DETECTED"
ALERT_TRIGGERED = "ALERT_TRIGGERED"
AWARD_DATES_REFRESHED = "AWARD_DATES_REFRESHED"

Handler = Callable[["Event"], None]


@dataclass(frozen=True)
class Event:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


_handlers: list[Handler] = []
_recent: list[Event] = []
_RECENT_CAP = 200


def subscribe(handler: Handler) -> None:
    _handlers.append(handler)


def recent(limit: int = 50) -> list[Event]:
    return list(_recent[-limit:])


def clear() -> None:
    """Test helper — wipe subscribers and the ring buffer."""
    _handlers.clear()
    _recent.clear()


def emit(name: str, **payload: Any) -> Event:
    event = Event(name=name, payload=payload)
    _recent.append(event)
    if len(_recent) > _RECENT_CAP:
        del _recent[:-_RECENT_CAP]
    log.info("event %s %s", name, payload)
    for handler in list(_handlers):
        try:
            handler(event)
        except Exception:
            log.exception("event handler failed for %s", name)
    return event
