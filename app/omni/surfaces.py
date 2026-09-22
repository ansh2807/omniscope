"""Declared outbound surfaces the site itself linked (spec §11).

App stores, GitHub and status pages are recorded only when a sampled page
linked them. We do not search for a GitHub org by name. A missing GitHub
link is empty, not 'they have no repo'.
"""
from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.engine.discovery.expander import classify as classify_link

STATUS_HOST = ("statuspage.io", "instatus.com", "status.io")


class SurfaceLink(BaseModel):
    kind: str
    url: str
    host: str = ""


class SurfaceIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    links: list[SurfaceLink] = Field(default_factory=list)
    methodology: str = (
        "Links are taken from sampled pages and sameAs. GitHub/app/status "
        "rows are not completed by name-search. Absence is empty, not zero.")


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def classify_surface(url: str) -> str | None:
    """Pure. None if this URL is not a declared surface we record."""
    if not url or not url.startswith("http"):
        return None
    platform = classify_link(url)
    if platform in {"appstore", "playstore"}:
        return platform
    host = _host(url)
    path = urlparse(url).path.lower()
    if host == "github.com" or host.endswith(".github.com"):
        parts = [p for p in path.split("/") if p]
        if parts and parts[0] not in {"pricing", "features", "login", "about"}:
            return "github"
        return None
    if any(host == h or host.endswith("." + h) for h in STATUS_HOST):
        return "status"
    if host.startswith("status.") or path.rstrip("/") == "/status":
        return "status"
    return None


def from_links(urls: list[str]) -> SurfaceIntel:
    """Pure over already-observed URLs."""
    links: list[SurfaceLink] = []
    seen: set[str] = set()
    for url in urls:
        kind = classify_surface(url)
        if not kind:
            continue
        clean = url.split("#")[0].rstrip("/")
        if clean in seen:
            continue
        seen.add(clean)
        links.append(SurfaceLink(kind=kind, url=clean, host=_host(clean)))
    if not links:
        return SurfaceIntel(
            assessed=True,
            reason="No app store, GitHub or status URL was linked from sampled pages.",
        )
    return SurfaceIntel(assessed=True, links=links[:20])
