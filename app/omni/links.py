"""Document link relations from sampled HTML and the homepage Link header.

canonical / author / publisher / manifest / amphtml and a few neighbours are
copied. Hrefs are not fetched. A listed /manifest.json is not an installed
PWA. author/publisher are not verified authorship and never become merge keys.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field
from selectolax.parser import HTMLParser

KEEP = {
    "canonical",
    "author",
    "publisher",
    "prev",
    "next",
    "manifest",
    "amphtml",
    "license",
    "privacy-policy",
    "terms-of-service",
    "search",
    "shortlink",
}
ALIASES = {"previous": "prev"}
_LINK = re.compile(r"<([^>]+)>\s*(?:;([^,]*))?", re.I)


class LinkRow(BaseModel):
    rel: str
    url: str
    host: str = ""
    via: str = "html"
    type: str = ""


class LinkIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    rows: list[LinkRow] = Field(default_factory=list)
    canonical: str = ""
    manifests: list[str] = Field(default_factory=list)
    methodology: str = (
        "link[rel] and a[rel] on sampled pages, plus the homepage HTTP Link "
        "header. Hrefs are copied, not fetched. A manifest URL is not a PWA "
        "install. author/publisher are not verified authorship and are not "
        "merge keys. stylesheet / preconnect / icon hints are out of scope "
        "here (see vendor hosts).")


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _norm_rel(name: str) -> str:
    return ALIASES.get((name or "").strip().lower(), (name or "").strip().lower())


def parse_link_header(value: str) -> list[tuple[str, list[str], str]]:
    """RFC 8288 subset: <url>; rel=... pairs. Not a complete header library."""
    out: list[tuple[str, list[str], str]] = []
    for match in _LINK.finditer(value or ""):
        href = (match.group(1) or "").strip()
        params = match.group(2) or ""
        rels: list[str] = []
        typ = ""
        for part in params.split(";"):
            if "=" not in part:
                continue
            key, _, raw = part.partition("=")
            key = key.strip().lower()
            raw = raw.strip().strip("\"'")
            if key == "rel":
                rels = [_norm_rel(x) for x in raw.split() if x]
            elif key == "type":
                typ = raw[:80]
        if href and rels:
            out.append((href, rels, typ))
    return out


def analyse_links(
    raw_html: list[tuple[str, str]],
    headers: dict[str, str] | None = None,
) -> LinkIntel:
    """Pure over already-fetched HTML and optional homepage response headers."""
    if not raw_html and not (headers or {}):
        return LinkIntel(assessed=False, reason="No pages were sampled.")
    rows: list[LinkRow] = []
    seen: set[tuple[str, str, str]] = set()
    canonical = ""
    manifests: list[str] = []

    def add(rel: str, url: str, via: str, typ: str = "") -> None:
        nonlocal canonical
        rel = _norm_rel(rel)
        if rel not in KEEP or not url:
            return
        if url.startswith(("#", "javascript:", "mailto:", "tel:")):
            return
        key = (rel, url.lower(), via)
        if key in seen:
            return
        seen.add(key)
        rows.append(LinkRow(
            rel=rel, url=url[:240], host=_host(url), via=via, type=typ[:80]))
        if rel == "canonical" and not canonical:
            canonical = url[:240]
        if rel == "manifest" and url not in manifests:
            manifests.append(url[:240])

    for page_url, html in raw_html:
        tree = HTMLParser(html or "")
        for node in tree.css("link[rel][href], a[rel][href]"):
            href = (node.attributes.get("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(page_url, href).split("#")[0]
            if not absolute.startswith("http"):
                continue
            typ = (node.attributes.get("type") or "").strip()
            for rel in (node.attributes.get("rel") or "").split():
                add(rel, absolute, "html", typ)
            if len(rows) >= 40:
                break
        if len(rows) >= 40:
            break

    raw = {k.lower(): v for k, v in (headers or {}).items() if v}
    home = raw_html[0][0] if raw_html else ""
    for href, rels, typ in parse_link_header(raw.get("link") or ""):
        absolute = urljoin(home, href).split("#")[0]
        if not absolute.startswith("http"):
            continue
        for rel in rels:
            add(rel, absolute, "header", typ)

    if not rows:
        return LinkIntel(
            assessed=True,
            reason="No canonical / author / manifest / HTTP Link relations on sampled pages.",
        )
    return LinkIntel(
        assessed=True,
        rows=rows[:40],
        canonical=canonical,
        manifests=manifests[:8],
    )
