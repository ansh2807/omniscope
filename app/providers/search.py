"""Search + news adapters over the existing licensed-search ensemble."""
from __future__ import annotations

from app.engine.discovery.search import search as ensemble_search
from app.omni.registry import record
from app.schemas import SearchHit


class EnsembleSearchProvider:
    name = "search_ensemble"

    async def search(self, query: str, *, limit: int = 8) -> list[SearchHit]:
        try:
            hits = await ensemble_search(query, limit=limit)
            record(self.name, ok=True)
            return hits
        except Exception as exc:  # noqa: BLE001
            record(self.name, ok=False, error=str(exc))
            return []

    async def get_news(self, query: str, *, limit: int = 8) -> list[SearchHit]:
        """News is the same ensemble with a news-biased query. No HTML scraping."""
        return await self.search(f"{query} news", limit=limit)


def search_provider() -> EnsembleSearchProvider:
    return EnsembleSearchProvider()
