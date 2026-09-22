"""Market map from licensed search (spec §18).

Participants are official websites that rank for a market query. This is not
TAM, share, or a complete industry census.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.omni.competitors import CompanyCompetitor, pick_competitors
from app.omni.keyless_web import duckduckgo_hits
from app.schemas import SearchHit


class MarketIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    query_used: str = ""
    participants: list[CompanyCompetitor] = Field(default_factory=list)
    methodology: str = (
        "Participants are distinct official websites from a licensed search "
        "for '{query} companies' / '{query} market', or DuckDuckGo Instant Answer "
        "when no search key is present. Directories are dropped. Market size, "
        "share and growth rates are not measured.")


def pick_participants(hits: list[SearchHit], self_domain: str = "",
                      *, limit: int = 8) -> list[CompanyCompetitor]:
    """Same official-site filter as competitors, slightly larger default list."""
    return pick_competitors(hits, self_domain or "_none_", limit=limit)


async def scan(entity_name: str, domain: str = "") -> MarketIntel:
    from app.providers.search import search_provider

    query = f"{entity_name} companies"
    hits = await search_provider().search(query, limit=10)
    if not hits:
        query = f"{entity_name} market"
        hits = await search_provider().search(query, limit=10)
    if not hits:
        query = f"{entity_name} companies"
        hits = await duckduckgo_hits(query, limit=10)
    if not hits:
        return MarketIntel(
            assessed=False,
            query_used=query,
            reason="Licensed search and DuckDuckGo Instant Answer both returned "
                   "no official-site market participants.",
        )
    people = pick_participants(hits, domain, limit=8)
    if not people:
        return MarketIntel(
            assessed=False, query_used=query,
            reason="Search returned only directories or the subject's own site.")
    return MarketIntel(assessed=True, query_used=query, participants=people)
