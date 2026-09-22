"""On-page conversion and media surfaces from already-fetched HTML (spec §8, §11).

Iframes, form actions, click-to-chat links and .pdf hrefs are copied from
sampled pages. Linked PDFs are listed, never fetched or OCR'd. A missing
Calendly embed is empty, not 'they have no booking page'. We do not invent
/brochure.pdf.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field
from selectolax.parser import HTMLParser

EMBED_HOSTS: tuple[tuple[str, str], ...] = (
    ("youtube.com", "youtube"),
    ("youtu.be", "youtube"),
    ("player.vimeo.com", "vimeo"),
    ("vimeo.com", "vimeo"),
    ("loom.com", "loom"),
    ("calendly.com", "calendly"),
    ("typeform.com", "typeform"),
    ("hsforms.com", "hubspot"),
    ("docs.google.com", "google_form"),
)


class OnPageHit(BaseModel):
    kind: str
    provider: str
    url: str
    page: str = ""


class OnPageIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    hits: list[OnPageHit] = Field(default_factory=list)
    methodology: str = (
        "Hits are iframe src, form action, click-to-chat and .pdf hrefs on "
        "sampled pages. PDFs are not downloaded. Absence is empty, not a "
        "claim the company has no booking flow or brochure.")


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _clean(url: str) -> str:
    return (url or "").split("#")[0].strip()


def classify_embed(url: str) -> str | None:
    """Provider for an iframe src, or None if empty."""
    if not url or not url.startswith(("http://", "https://", "//")):
        return None
    if url.startswith("//"):
        url = "https:" + url
    host = _host(url)
    path = urlparse(url).path.lower()
    if host.endswith("docs.google.com") and "/forms" not in path:
        return None
    for suffix, provider in EMBED_HOSTS:
        if host == suffix or host.endswith("." + suffix):
            return provider
    return "iframe"


def classify_chat(url: str) -> str | None:
    if not url or not url.startswith("http"):
        return None
    host = _host(url)
    path = urlparse(url).path.lower()
    if host in {"wa.me", "api.whatsapp.com"} or (
            host.endswith("whatsapp.com") and "/send" in path):
        return "whatsapp"
    if host in {"t.me", "telegram.me"}:
        return "telegram"
    return None


def _pdf_url(absolute: str) -> bool:
    path = urlparse(absolute).path.lower()
    return path.endswith(".pdf")


def analyse_onpage(raw_html: list[tuple[str, str]]) -> OnPageIntel:
    """Pure over already-fetched HTML. Does not fetch linked PDFs."""
    if not raw_html:
        return OnPageIntel(assessed=False, reason="No pages were sampled.")
    hits: list[OnPageHit] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, provider: str, url: str, page: str) -> None:
        url = _clean(url)
        if not url:
            return
        key = (kind, url)
        if key in seen:
            return
        seen.add(key)
        hits.append(OnPageHit(kind=kind, provider=provider, url=url[:300], page=page))

    for page_url, html in raw_html:
        host = _host(page_url)
        tree = HTMLParser(html or "")
        for node in tree.css("iframe[src]"):
            src = (node.attributes.get("src") or "").strip()
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = urljoin(page_url, src)
            provider = classify_embed(src)
            if provider:
                add("embed", provider, src, page_url)
        for node in tree.css("form"):
            action = (node.attributes.get("action") or "").strip()
            if action.startswith("mailto:"):
                add("form", "mailto", action, page_url)
                continue
            if not action or action.startswith("#"):
                add("form", "first_party", page_url, page_url)
                continue
            absolute = urljoin(page_url, action).split("#")[0]
            if classify_chat(absolute):
                add("form", classify_chat(absolute) or "chat", absolute, page_url)
            elif _host(absolute) == host:
                add("form", "first_party", absolute, page_url)
            elif absolute.startswith("http"):
                add("form", "third_party", absolute, page_url)
        for node in tree.css("a[href]"):
            href = (node.attributes.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:")):
                continue
            if href.startswith("mailto:"):
                continue
            absolute = urljoin(page_url, href).split("#")[0]
            chat = classify_chat(absolute)
            if chat:
                add("chat", chat, absolute, page_url)
                continue
            if _pdf_url(absolute):
                provider = "same_host" if _host(absolute) == host else "off_host"
                add("pdf", provider, absolute, page_url)
    return OnPageIntel(assessed=True, hits=hits[:40])
