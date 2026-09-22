"""Keyless official-site and related-entity lookups.

Wikipedia citations, Wikidata P856, and DuckDuckGo Instant Answer. No licensed
search key. These copy what those APIs returned; they do not invent rivals or
rankings.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote_plus, urlparse

from app.engine.http import fetch
from app.engine.discovery.wikidata_identity import parse_official_ids
from app.omni.open_sources import official_site_from_wikipedia
from app.schemas import SearchHit

SKIP_HOSTS = (
    "wikipedia.org", "wikidata.org", "linkedin.com", "facebook.com", "instagram.com",
    "youtube.com", "x.com", "twitter.com", "crunchbase.com", "reddit.com",
    "quora.com", "medium.com", "github.com", "duckduckgo.com",
)


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _skipped(url: str, extra: tuple[str, ...] = ()) -> bool:
    host = _host(url)
    if not host:
        return True
    banned = SKIP_HOSTS + extra
    return any(token in host for token in banned)


def _shares_tokens(query: str, label: str) -> bool:
    q = {t for t in re.split(r"\W+", (query or "").lower()) if len(t) > 2}
    n = {t for t in re.split(r"\W+", (label or "").lower()) if len(t) > 2}
    return bool(q and n and q & n)


def parse_wikidata_official(entity: dict, extra_skip: tuple[str, ...] = ()) -> str:
    """P856 official website from a wbgetentities entity object."""
    claims = entity.get("claims") if isinstance(entity, dict) else None
    if not isinstance(claims, dict):
        return ""
    for snak in claims.get("P856") or []:
        if not isinstance(snak, dict):
            continue
        value = ((snak.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, str) and value.startswith("http") and not _skipped(value, extra_skip):
            return value
    return ""


def pick_wikidata_id(payload: dict, query: str) -> str:
    rows = (payload or {}).get("search") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "")
        ident = str(row.get("id") or "")
        if ident.startswith("Q") and _shares_tokens(query, label):
            return ident
    return ""


def parse_ddg_hits(payload: dict, query: str, *, limit: int = 10) -> list[SearchHit]:
    """RelatedTopics / Results / AbstractURL → search-shaped hits."""
    out: list[SearchHit] = []
    seen: set[str] = set()

    def add(url: str, title: str) -> None:
        if not url.startswith("http") or _skipped(url) or url in seen:
            return
        seen.add(url)
        label = (title or _host(url)).strip()[:200]
        out.append(SearchHit(
            query=query, title=label, url=url, snippet=label,
            provider="duckduckgo"))

    if isinstance(payload, dict):
        abstract = str(payload.get("AbstractURL") or "")
        heading = str(payload.get("Heading") or query)
        if abstract:
            add(abstract, heading)
        for row in payload.get("Results") or []:
            if isinstance(row, dict):
                add(str(row.get("FirstURL") or ""), str(row.get("Text") or ""))
        _walk_topics(payload.get("RelatedTopics"), add)
    return out[:limit]


def _walk_topics(node, add) -> None:
    if isinstance(node, list):
        for item in node:
            _walk_topics(item, add)
        return
    if not isinstance(node, dict):
        return
    if "Topics" in node:
        _walk_topics(node.get("Topics"), add)
        return
    add(str(node.get("FirstURL") or ""), str(node.get("Text") or ""))


def official_from_ddg_hits(hits: list[SearchHit], name: str) -> str:
    for hit in hits:
        if _shares_tokens(name, hit.title) or _shares_tokens(name, _host(hit.url)):
            return hit.url
    return hits[0].url if hits else ""


def p856_matches_domain(entity: dict, domain: str) -> bool:
    """True only when Wikidata already claims this host as the official website."""
    want = (domain or "").lower().removeprefix("www.")
    if not want:
        return False
    claims = entity.get("claims") if isinstance(entity, dict) else None
    if not isinstance(claims, dict):
        return False
    for snak in claims.get("P856") or []:
        if not isinstance(snak, dict):
            continue
        value = ((snak.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, str) and _host(value) == want:
            return True
    return False


async def official_ids_for_site(name: str, domain: str) -> dict[str, object]:
    """Official IDs from a Wikidata item whose P856 host matches *domain*."""
    empty: dict[str, object] = {"wikidata_id": "", "official_ids": {},
                                "official_id_urls": {}}
    query = (name or "").strip()
    host = (domain or "").lower().removeprefix("www.")
    if len(query) < 3 or not host:
        return empty
    search = await fetch(
        "https://www.wikidata.org/w/api.php?action=wbsearchentities"
        f"&search={quote_plus(query)}&language=en&format=json&limit=5",
        check_robots=False)
    if not search.ok:
        return empty
    try:
        packed = json.loads(search.text)
    except json.JSONDecodeError:
        return empty
    ident = pick_wikidata_id(packed, query)
    if not ident:
        return empty
    entity_resp = await fetch(
        "https://www.wikidata.org/w/api.php?action=wbgetentities"
        f"&ids={quote_plus(ident)}&props=claims|labels&format=json",
        check_robots=False)
    if not entity_resp.ok:
        return empty
    try:
        body = json.loads(entity_resp.text)
    except json.JSONDecodeError:
        return empty
    row = ((body.get("entities") or {}).get(ident) or {})
    if not p856_matches_domain(row, host):
        return empty
    parsed = parse_official_ids(row)
    return {
        "wikidata_id": ident,
        "official_ids": {k: v for k, v in parsed.items() if not k.endswith("_url")},
        "official_id_urls": {k[:-4]: v for k, v in parsed.items() if k.endswith("_url")},
    }


async def wikidata_official_site(name: str, extra_skip: tuple[str, ...] = ()) -> str:
    query = (name or "").strip()
    if len(query) < 3:
        return ""
    search = await fetch(
        "https://www.wikidata.org/w/api.php?action=wbsearchentities"
        f"&search={quote_plus(query)}&language=en&format=json&limit=5",
        check_robots=False)
    if not search.ok:
        return ""
    try:
        packed = json.loads(search.text)
    except json.JSONDecodeError:
        return ""
    ident = pick_wikidata_id(packed, query)
    if not ident:
        return ""
    entity = await fetch(
        "https://www.wikidata.org/w/api.php?action=wbgetentities"
        f"&ids={quote_plus(ident)}&props=claims&format=json",
        check_robots=False)
    if not entity.ok:
        return ""
    try:
        body = json.loads(entity.text)
    except json.JSONDecodeError:
        return ""
    row = ((body.get("entities") or {}).get(ident) or {})
    return parse_wikidata_official(row, extra_skip)


async def duckduckgo_hits(query: str, *, limit: int = 10) -> list[SearchHit]:
    text = (query or "").strip()
    if len(text) < 3:
        return []
    resp = await fetch(
        "https://api.duckduckgo.com/?"
        f"q={quote_plus(text)}&format=json&no_html=1&no_redirect=1",
        check_robots=False)
    if not resp.ok:
        return []
    try:
        packed = json.loads(resp.text) if resp.text else {}
    except json.JSONDecodeError:
        return []
    if not isinstance(packed, dict):
        return []
    return parse_ddg_hits(packed, text, limit=limit)


async def resolve_official_site(name: str, skip_hosts: tuple[str, ...]) -> str:
    """Wikipedia citations, then Wikidata P856, then DuckDuckGo Instant Answer."""
    wiki = await official_site_from_wikipedia(name, skip_hosts)
    if wiki:
        return wiki
    wikidata = await wikidata_official_site(name, skip_hosts)
    if wikidata:
        return wikidata
    hits = await duckduckgo_hits(name, limit=8)
    return official_from_ddg_hits(hits, name)
