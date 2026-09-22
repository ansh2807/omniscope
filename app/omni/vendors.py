"""Off-host script and resource hosts on sampled pages (spec §8, §11).

Hosts come from script src and link rel=preconnect / dns-prefetch / stylesheet.
A host is not a product name, a spend figure, or proof of a vendor contract.
Body copy like 'we use HubSpot' does not count.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field
from selectolax.parser import HTMLParser


class VendorHost(BaseModel):
    host: str
    via: str
    url: str = ""
    page: str = ""


class VendorIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    hosts: list[VendorHost] = Field(default_factory=list)
    unique: list[str] = Field(default_factory=list)
    methodology: str = (
        "Hosts are copied from off-origin script src and link preconnect / "
        "dns-prefetch / stylesheet hrefs. This is not a vendor contract, "
        "spend, or a complete tag-manager inventory.")


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def analyse_vendors(raw_html: list[tuple[str, str]]) -> VendorIntel:
    """Pure over already-fetched HTML. Does not fetch the third-party URLs."""
    if not raw_html:
        return VendorIntel(assessed=False, reason="No pages were sampled.")
    rows: list[VendorHost] = []
    seen: set[tuple[str, str]] = set()
    unique: list[str] = []
    seen_host: set[str] = set()

    def add(host: str, via: str, url: str, page: str) -> None:
        host = (host or "").strip().lower()
        if not host:
            return
        key = (host, via)
        if key in seen:
            return
        seen.add(key)
        rows.append(VendorHost(host=host[:80], via=via, url=url[:240], page=page))
        if host not in seen_host:
            seen_host.add(host)
            unique.append(host)

    for page_url, html in raw_html:
        origin = _host(page_url)
        tree = HTMLParser(html or "")
        for node in tree.css("script[src]"):
            src = (node.attributes.get("src") or "").strip()
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = urljoin(page_url, src)
            if not src.startswith("http"):
                continue
            host = _host(src)
            if host and host != origin:
                add(host, "script", src, page_url)
        for node in tree.css("link[href]"):
            rels = (node.attributes.get("rel") or "").lower().split()
            href = (node.attributes.get("href") or "").strip()
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = urljoin(page_url, href)
            if not href.startswith("http"):
                continue
            host = _host(href)
            if not host or host == origin:
                continue
            via = ""
            if "preconnect" in rels:
                via = "preconnect"
            elif "dns-prefetch" in rels:
                via = "dns-prefetch"
            elif "stylesheet" in rels:
                via = "stylesheet"
            if via:
                add(host, via, href, page_url)
        if len(rows) >= 40:
            break
    if not rows:
        return VendorIntel(
            assessed=True,
            reason="No off-host script, preconnect or stylesheet hosts on sampled pages.",
        )
    return VendorIntel(assessed=True, hosts=rows[:40], unique=unique[:30])
