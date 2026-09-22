"""Web fetch adapter — every crawl goes through the SSRF-safe client."""
from __future__ import annotations

from app.engine.http import Fetched, fetch
from app.omni.registry import record


class AtlasWebProvider:
    name = "http"

    async def fetch_page(self, url: str) -> Fetched:
        page = await fetch(url)
        record(self.name, ok=page.ok, error=page.error or "")
        return page


def web_provider() -> AtlasWebProvider:
    return AtlasWebProvider()
