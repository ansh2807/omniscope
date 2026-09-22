"""Keyless public APIs used to enrich reports.

Picked from https://github.com/public-apis/public-apis (auth = No):
  Archive.org, Hacker News (official search), Domainsdb.info, Datamuse,
  Nominatim, REST Countries. Wikipedia stays in discovery/keyless.

Every figure is copied from the JSON the endpoint returned. Empty stays
unavailable. These are not traffic, rank, or sentiment scores.
"""
from __future__ import annotations

import json
from urllib.parse import quote_plus, urlparse

from pydantic import BaseModel, Field

from app.engine.discovery.keyless import (
    _plausible_official_link,
    wikipedia as wiki_lookup,
)
from app.engine.http import fetch
from app.schemas import SearchHit

GENERIC_TLDS = {
    "com", "org", "net", "edu", "gov", "mil", "int", "io", "ai", "app", "dev",
    "co", "xyz", "online", "shop", "site", "tech", "info", "biz", "name", "pro",
    "tv", "me", "cc", "ws", "club", "live", "news", "blog", "store", "cloud",
}

HN_FALLBACK = (
    "Items are Hacker News stories matching the name or domain. Points and "
    "comment counts are what HN returned. This is not press circulation or "
    "sentiment."
)


class WaybackIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    first_capture: str = ""
    last_capture: str = ""
    last_url: str = ""
    methodology: str = (
        "Internet Archive CDX + availability API. Timestamps are capture "
        "times, not the date the company was founded.")


class DomainRow(BaseModel):
    domain: str
    created: str = ""
    country: str = ""


class DomainIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    rows: list[DomainRow] = Field(default_factory=list)
    methodology: str = (
        "domainsdb.info registered-name search on the second-level label. "
        "A shared label is not proof the same company owns every result.")


class WordRow(BaseModel):
    word: str
    score: int | None = None


class WordIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    rows: list[WordRow] = Field(default_factory=list)
    methodology: str = (
        "Datamuse means-like associations. Scores are the API's similarity "
        "rank, not search volume.")


class GeoIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    label: str = ""
    lat: str = ""
    lon: str = ""
    methodology: str = (
        "Nominatim geocode of an address the site already printed. This is "
        "not a verified registered office.")


class CountryIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    tld: str = ""
    name: str = ""
    region: str = ""
    capital: str = ""
    methodology: str = (
        "REST Countries record for a country-code TLD. A .in domain is not "
        "proof the company is incorporated in India.")


class WikiIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    title: str = ""
    url: str = ""
    extract: str = ""


class OpenSourceIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    wayback: WaybackIntel = Field(default_factory=WaybackIntel)
    domains: DomainIntel = Field(default_factory=DomainIntel)
    words: WordIntel = Field(default_factory=WordIntel)
    geo: GeoIntel = Field(default_factory=GeoIntel)
    country: CountryIntel = Field(default_factory=CountryIntel)
    wikipedia: WikiIntel = Field(default_factory=WikiIntel)
    hn_stories: int = 0
    methodology: str = (
        "Keyless endpoints listed on public-apis. Licensed search is still "
        "used when a key is configured.")


def _json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _sld(domain: str) -> str:
    host = (domain or "").lower().removeprefix("www.")
    parts = [p for p in host.split(".") if p]
    return parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")


def _cctld(domain: str) -> str:
    host = (domain or "").lower().removeprefix("www.")
    parts = [p for p in host.split(".") if p]
    if len(parts) < 2:
        return ""
    tld = parts[-1]
    if tld == "uk" and len(parts) >= 2:
        return "gb"
    if len(tld) != 2 or tld in GENERIC_TLDS:
        return ""
    return tld


def _stamp(raw: str) -> str:
    digits = "".join(c for c in (raw or "") if c.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return (raw or "")[:10]


async def wayback(domain: str) -> WaybackIntel:
    host = (domain or "").lower().removeprefix("www.")
    out = WaybackIntel()
    if not host:
        out.reason = "No domain to look up in the Internet Archive."
        return out
    first = await fetch(
        f"https://web.archive.org/cdx/search/cdx?url={quote_plus(host)}"
        f"&output=json&fl=timestamp&filter=statuscode:200&limit=1",
        check_robots=False)
    data = _json(first.text) if first.ok else None
    if isinstance(data, list) and len(data) >= 2 and data[1]:
        out.first_capture = _stamp(str(data[1][0]))
    avail = await fetch(
        f"https://archive.org/wayback/available?url={quote_plus(host)}",
        check_robots=False)
    packed = _json(avail.text) if avail.ok else None
    snap = {}
    if isinstance(packed, dict):
        snap = ((packed.get("archived_snapshots") or {}).get("closest") or {})
    if snap.get("timestamp"):
        out.last_capture = _stamp(str(snap["timestamp"]))
        out.last_url = str(snap.get("url") or "")
    if out.first_capture or out.last_capture:
        out.assessed = True
        return out
    out.reason = "Internet Archive returned no snapshot for this host."
    return out


async def hacker_news(entity_name: str, domain: str, *, limit: int = 8) -> list[SearchHit]:
    query = " ".join(p for p in ((entity_name or "").strip(),
                                 (domain or "").removeprefix("www.")) if p)
    if len(query) < 3:
        return []
    url = (f"https://hn.algolia.com/api/v1/search?query={quote_plus(query)}"
           f"&tags=story&hitsPerPage={limit}")
    resp = await fetch(url, check_robots=False)
    if not resp.ok:
        return []
    packed = _json(resp.text)
    rows = packed.get("hits") if isinstance(packed, dict) else None
    if not isinstance(rows, list):
        return []
    hits: list[SearchHit] = []
    tokens = {t for t in query.lower().replace(".", " ").split() if len(t) > 2}
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = (row.get("title") or "").strip()
        href = (row.get("url") or "").strip()
        object_id = str(row.get("objectID") or "")
        if not href and object_id:
            href = f"https://news.ycombinator.com/item?id={object_id}"
        blob = f"{title} {href}".lower()
        if tokens and not any(t in blob for t in tokens):
            continue
        if not title or not href:
            continue
        points = row.get("points")
        comments = row.get("num_comments")
        snippet = " · ".join(
            p for p in (
                f"{points} points" if isinstance(points, int) else "",
                f"{comments} comments" if isinstance(comments, int) else "",
                (row.get("created_at") or "")[:10],
            ) if p)
        hits.append(SearchHit(
            query=query, title=title[:200], url=href, snippet=snippet,
            provider="hackernews"))
    return hits[:limit]


async def related_domains(domain: str, *, limit: int = 8) -> DomainIntel:
    label = _sld(domain)
    out = DomainIntel()
    if len(label) < 3:
        out.reason = "Second-level domain is too short for a registry search."
        return out
    resp = await fetch(
        f"https://api.domainsdb.info/v1/domains/search?limit={limit}"
        f"&domain={quote_plus(label)}",
        check_robots=False)
    packed = _json(resp.text) if resp.ok else None
    rows = packed.get("domains") if isinstance(packed, dict) else None
    if not isinstance(rows, list):
        out.reason = "domainsdb.info did not return a domain list."
        return out
    seen: set[str] = set()
    host = (domain or "").lower().removeprefix("www.")
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = (item.get("domain") or "").strip().lower()
        if not name or name in seen or name == host:
            continue
        seen.add(name)
        created = str(item.get("create_date") or item.get("ADate") or "")[:10]
        out.rows.append(DomainRow(
            domain=name, created=created,
            country=str(item.get("country") or "")[:40]))
        if len(out.rows) >= limit:
            break
    if out.rows:
        out.assessed = True
        return out
    out.reason = "No other registered names shared this label."
    return out


async def related_words(term: str, *, limit: int = 12) -> WordIntel:
    out = WordIntel()
    seed = (term or "").strip()
    if len(seed) < 3:
        out.reason = "Need a longer phrase for Datamuse."
        return out
    resp = await fetch(
        f"https://api.datamuse.com/words?ml={quote_plus(seed)}&max={limit}",
        check_robots=False)
    rows = _json(resp.text) if resp.ok else None
    if not isinstance(rows, list):
        out.reason = "Datamuse did not return associations."
        return out
    for item in rows:
        if not isinstance(item, dict):
            continue
        word = (item.get("word") or "").strip()
        if not word:
            continue
        score = item.get("score")
        out.rows.append(WordRow(
            word=word[:80],
            score=score if isinstance(score, int) else None))
    if out.rows:
        out.assessed = True
        return out
    out.reason = "Datamuse returned no associations for this phrase."
    return out


async def geocode(address: str) -> GeoIntel:
    out = GeoIntel()
    text = " ".join((address or "").split())
    if len(text) < 12 or len(text.split()) < 3:
        out.reason = "No printed street address long enough to geocode."
        return out
    resp = await fetch(
        "https://nominatim.openstreetmap.org/search"
        f"?q={quote_plus(text)}&format=json&limit=1",
        check_robots=False)
    rows = _json(resp.text) if resp.ok else None
    if not isinstance(rows, list) or not rows:
        out.reason = "Nominatim did not match the printed address."
        return out
    hit = rows[0] if isinstance(rows[0], dict) else {}
    out.label = str(hit.get("display_name") or "")[:200]
    out.lat = str(hit.get("lat") or "")
    out.lon = str(hit.get("lon") or "")
    if out.lat and out.lon:
        out.assessed = True
        return out
    out.reason = "Nominatim returned a row without coordinates."
    return out


async def country_for_domain(domain: str) -> CountryIntel:
    out = CountryIntel()
    tld = _cctld(domain)
    out.tld = tld
    if not tld:
        out.reason = "Domain TLD is generic, so no country record is attached."
        return out
    resp = await fetch(
        f"https://restcountries.com/v3.1/alpha/{quote_plus(tld)}",
        check_robots=False)
    rows = _json(resp.text) if resp.ok else None
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    name = ((row.get("name") or {}).get("common") if isinstance(row.get("name"), dict)
            else "") or ""
    capitals = row.get("capital") if isinstance(row.get("capital"), list) else []
    out.name = str(name)[:80]
    out.region = str(row.get("region") or "")[:40]
    out.capital = str(capitals[0] if capitals else "")[:40]
    if out.name:
        out.assessed = True
        return out
    out.reason = f"REST Countries has no record for TLD .{tld}."
    return out


async def wikipedia_card(name: str) -> WikiIntel:
    out = WikiIntel()
    wiki = await wiki_lookup(name)
    if wiki.get("title"):
        out.assessed = True
        out.title = str(wiki.get("title") or "")
        out.url = str(wiki.get("url") or "")
        out.extract = str(wiki.get("extract") or "")[:800]
        return out
    out.reason = "No Wikipedia page title matched this name."
    return out


async def official_site_from_wikipedia(name: str, skip_hosts: tuple[str, ...]) -> str:
    """First Wikipedia citation that looks like the entity's own site."""
    wiki = await wiki_lookup(name)
    for href in wiki.get("links") or []:
        if not _plausible_official_link(href, name, ""):
            continue
        host = urlparse(href).netloc.lower()
        if host and not any(token in host for token in skip_hosts):
            return href
    return ""


async def collect(entity_name: str, domain: str, *, address: str = "") -> OpenSourceIntel:
    wayback_intel = await wayback(domain)
    domain_intel = await related_domains(domain)
    word_intel = await related_words(entity_name or _sld(domain))
    geo_intel = await geocode(address)
    country_intel = await country_for_domain(domain)
    wiki_intel = await wikipedia_card(entity_name)
    hn = await hacker_news(entity_name, domain)
    assessed = any((
        wayback_intel.assessed, domain_intel.assessed, word_intel.assessed,
        geo_intel.assessed, country_intel.assessed, wiki_intel.assessed, hn,
    ))
    reason = "" if assessed else (
        "Public keyless APIs returned nothing usable for this subject.")
    return OpenSourceIntel(
        assessed=assessed, reason=reason, wayback=wayback_intel,
        domains=domain_intel, words=word_intel, geo=geo_intel,
        country=country_intel, wikipedia=wiki_intel, hn_stories=len(hn))
