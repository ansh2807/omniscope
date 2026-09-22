"""Per-analysis usage counters (observed work, not a billing invoice).

Search calls are counted via a contextvar so concurrent jobs do not share a
global integer. HTTP page counts stay local to the crawl that produced them.
"""
from __future__ import annotations

from contextvars import ContextVar

_search_calls: ContextVar[int] = ContextVar("omni_search_calls", default=0)


def reset_search() -> None:
    _search_calls.set(0)


def add_search() -> None:
    _search_calls.set(_search_calls.get() + 1)


def search_calls() -> int:
    return _search_calls.get()
