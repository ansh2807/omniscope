"""Search provider adapters.

Three licensed APIs supported, plus a 'none' mode so the engine still runs (with a
warning) when no search key is configured. Never scrapes a search engine's HTML —
that breaks their ToS and gets you blocked within an hour.
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.config import settings
from app.engine.http import fetch
from app.omni.search_context import active_serper_key, guest_serper_key
from app.omni.usage import add_search
from app.schemas import SearchHit


async def search(query: str, *, limit: int = 8) -> list[SearchHit]:
    """Search through the configured provider ensemble and merge URL consensus.

    One provider remains useful; two or three let the engine distinguish a stable result from
    a provider-specific ranking artefact.  The selected provider is always queried first.
    """
    providers = _available_providers()
    if not providers:
        return []
    add_search()
    if not settings.search_ensemble:
        providers = providers[:1]
    providers = providers[:max(1, settings.search_max_providers)]
    batches = await asyncio.gather(
        *(_search_one(provider, query, limit) for provider in providers),
        return_exceptions=True,
    )
    hits = [hit for batch in batches if isinstance(batch, list) for hit in batch]
    return _merge(hits, limit)


def _available_providers() -> list[str]:
    if guest_serper_key():
        return ["serper"]
    provider = (settings.search_provider or "none").lower()
    configured = []
    if settings.serper_api_key:
        configured.append("serper")
    if settings.brave_api_key:
        configured.append("brave")
    if settings.google_cse_key and settings.google_cse_cx:
        configured.append("google_cse")
    if provider in ("all", "ensemble"):
        return configured
    if provider == "none" or provider not in configured:
        return []
    return [provider] + [p for p in configured if p != provider]


async def _search_one(provider: str, query: str, limit: int) -> list[SearchHit]:
    if provider == "serper":
        return await _serper(query, limit)
    if provider == "brave":
        return await _brave(query, limit)
    if provider == "google_cse":
        return await _cse(query, limit)
    return []


def _canonical(url: str) -> str:
    try:
        parts = urlsplit(url)
        kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if not k.lower().startswith("utm_") and k.lower() not in
                {"gclid", "fbclid", "ref", "ref_src", "source"}]
        path = parts.path.rstrip("/") or "/"
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower().replace("www.", ""),
                           path, urlencode(kept), ""))
    except Exception:
        return url


def _merge(hits: list[SearchHit], limit: int) -> list[SearchHit]:
    grouped: dict[str, list[SearchHit]] = {}
    for hit in hits:
        if hit.url:
            grouped.setdefault(_canonical(hit.url), []).append(hit)
    merged: list[SearchHit] = []
    for url, rows in grouped.items():
        rows.sort(key=lambda h: (h.rank or 999, -len(h.snippet or "")))
        best = rows[0]
        providers = list(dict.fromkeys(
            p for row in rows for p in (row.providers or [row.provider]) if p))
        longest = max(rows, key=lambda h: len(h.snippet or ""))
        merged.append(best.model_copy(update={
            "url": url,
            "snippet": longest.snippet,
            "providers": providers,
            "provider": "+".join(providers),
            "rank": min((h.rank or 999) for h in rows),
        }))
    merged.sort(key=lambda h: (-len(h.providers), h.rank or 999,
                               -len(h.snippet or "")))
    return merged[:limit]


async def _serper(query: str, limit: int) -> list[SearchHit]:
    r = await fetch(
        "https://google.serper.dev/search",
        method="POST",
        json_body={"q": query, "num": limit, "gl": "in", "hl": "en"},
        headers={"X-API-KEY": active_serper_key(), "Content-Type": "application/json"},
        check_robots=False, use_cache=False,
    )
    if not r.ok:
        return []
    try:
        data = json.loads(r.text)
    except json.JSONDecodeError:
        return []
    return [SearchHit(query=query, title=o.get("title", ""), url=o.get("link", ""),
                      snippet=o.get("snippet", ""), provider="serper",
                      providers=["serper"], rank=i)
            for i, o in enumerate(data.get("organic", [])[:limit], 1) if o.get("link")]


async def _brave(query: str, limit: int) -> list[SearchHit]:
    r = await fetch(
        "https://api.search.brave.com/res/v1/web/search?" + urlencode({
            "q": query, "count": limit, "country": "IN"}),
        headers={"X-Subscription-Token": settings.brave_api_key, "Accept": "application/json"},
        check_robots=False, use_cache=False,
    )
    if not r.ok:
        return []
    try:
        data = json.loads(r.text)
    except json.JSONDecodeError:
        return []
    return [SearchHit(query=query, title=o.get("title", ""), url=o.get("url", ""),
                      snippet=o.get("description", ""), provider="brave",
                      providers=["brave"], rank=i)
            for i, o in enumerate((data.get("web", {}).get("results") or [])[:limit], 1)
            if o.get("url")]


async def _cse(query: str, limit: int) -> list[SearchHit]:
    url = "https://www.googleapis.com/customsearch/v1?" + urlencode({
        "key": settings.google_cse_key, "cx": settings.google_cse_cx,
        "q": query, "num": min(limit, 10), "gl": "in",
    })
    r = await fetch(url, check_robots=False, use_cache=False)
    if not r.ok:
        return []
    try:
        data = json.loads(r.text)
    except json.JSONDecodeError:
        return []
    return [SearchHit(query=query, title=o.get("title", ""), url=o.get("link", ""),
                      snippet=o.get("snippet", ""), provider="google_cse",
                      providers=["google_cse"], rank=i)
            for i, o in enumerate(data.get("items", [])[:limit], 1) if o.get("link")]
