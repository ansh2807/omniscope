"""Published verification tags, rel=me and sameAs (spec §11, §23).

A google-site-verification meta means the page printed that tag. It is not
proof Google verified the business. rel=me and JSON-LD sameAs are declared
identity URLs, not a confirmed same-as merge — we never fetch those URLs
and they never become merge keys.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field
from selectolax.parser import HTMLParser

from app.engine.collectors.web import _jsonld, _meta

VERIFY_META = (
    ("google-site-verification", "google"),
    ("facebook-domain-verification", "facebook"),
    ("msvalidate.01", "bing"),
    ("p:domain_verify", "pinterest"),
    ("yandex-verification", "yandex"),
)


class RelMe(BaseModel):
    url: str
    host: str = ""


class SameAsRow(BaseModel):
    url: str
    host: str = ""
    via: str = ""


class ClaimsIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    verifications: list[str] = Field(default_factory=list)
    rel_me: list[RelMe] = Field(default_factory=list)
    same_as: list[SameAsRow] = Field(default_factory=list)
    methodology: str = (
        "Verification rows record that a well-known meta name was present. "
        "The token is not stored and this is not a Search Console status. "
        "rel=me and sameAs hrefs are copied, not fetched, and never become "
        "merge keys. A sameAs host is not a follower count.")


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _type_names(entity: dict) -> list[str]:
    raw = entity.get("@type")
    if isinstance(raw, str):
        return [raw.split("/")[-1]]
    names: list[str] = []
    for item in raw or []:
        if isinstance(item, str):
            names.append(item.split("/")[-1])
    return names


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _href(value: Any, page_url: str) -> str:
    if isinstance(value, dict):
        raw = value.get("url") or value.get("@id") or ""
    elif isinstance(value, str):
        raw = value
    else:
        return ""
    raw = raw.strip()
    if not raw or raw.startswith(("#", "javascript:", "mailto:", "tel:")):
        return ""
    absolute = urljoin(page_url, raw).split("#")[0]
    if not absolute.startswith("http"):
        return ""
    return absolute


def verification_kinds(html: str) -> list[str]:
    """Meta names only. Body copy is ignored."""
    found: list[str] = []
    for name, kind in VERIFY_META:
        if _meta(html or "", name):
            if kind not in found:
                found.append(kind)
    return found


def rel_me_links(page_url: str, html: str) -> list[RelMe]:
    """link/a rel=me hrefs. 'media' is not me."""
    if not html:
        return []
    tree = HTMLParser(html)
    out: list[RelMe] = []
    seen: set[str] = set()
    for node in tree.css("link[rel], a[rel]"):
        rel = (node.attributes.get("rel") or "").lower().split()
        if "me" not in rel:
            continue
        href = (node.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(page_url, href).split("#")[0]
        if not absolute.startswith("http"):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append(RelMe(url=absolute, host=_host(absolute)))
        if len(out) >= 12:
            break
    return out


def same_as_links(page_url: str, html: str) -> list[SameAsRow]:
    """JSON-LD sameAs URLs. Body copy is ignored. Hrefs are not fetched."""
    if not html:
        return []
    out: list[SameAsRow] = []
    seen: set[str] = set()
    for entity in _jsonld(html or ""):
        if not isinstance(entity, dict) or entity.get("sameAs") is None:
            continue
        types = _type_names(entity)
        via = next((name for name in (
            "Organization", "LocalBusiness", "OnlineBusiness", "Corporation",
            "Person", "WebSite", "Brand") if name in types),
            (types[0] if types else "schema"))
        for item in _as_list(entity.get("sameAs")):
            absolute = _href(item, page_url)
            if not absolute or absolute in seen:
                continue
            seen.add(absolute)
            out.append(SameAsRow(url=absolute, host=_host(absolute), via=via))
            if len(out) >= 16:
                return out
    return out


def analyse_claims(raw_html: list[tuple[str, str]]) -> ClaimsIntel:
    """Pure over already-fetched HTML."""
    if not raw_html:
        return ClaimsIntel(assessed=False, reason="No pages were sampled.")
    kinds: list[str] = []
    links: list[RelMe] = []
    aliases: list[SameAsRow] = []
    seen_link: set[str] = set()
    seen_alias: set[str] = set()
    for url, html in raw_html:
        for kind in verification_kinds(html or ""):
            if kind not in kinds:
                kinds.append(kind)
        for row in rel_me_links(url, html or ""):
            if row.url in seen_link:
                continue
            seen_link.add(row.url)
            links.append(row)
        for row in same_as_links(url, html or ""):
            if row.url in seen_alias:
                continue
            seen_alias.add(row.url)
            aliases.append(row)
    if not kinds and not links and not aliases:
        return ClaimsIntel(
            assessed=True,
            reason="No verification meta, rel=me or sameAs on sampled pages.",
        )
    return ClaimsIntel(
        assessed=True,
        verifications=kinds[:8],
        rel_me=links[:12],
        same_as=aliases[:16],
    )
