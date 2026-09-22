"""Typed provider capabilities. New vendors implement these; engines stay vendor-free."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.engine.http import Fetched
from app.schemas import SearchHit


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, limit: int = 8) -> list[SearchHit]:
        ...


@runtime_checkable
class WebProvider(Protocol):
    name: str

    async def fetch_page(self, url: str) -> Fetched:
        ...


@runtime_checkable
class NewsProvider(Protocol):
    name: str

    async def get_news(self, query: str, *, limit: int = 8) -> list[SearchHit]:
        ...
