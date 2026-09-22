"""First-party RSS/Atom feed intelligence.

Only feeds the homepage advertises are fetched. Conventional /rss.xml is never
probed. Off-host feed URLs are dropped. Dates come from feed fields, never
from titles. No feed advertised → UNAVAILABLE, not an empty blog.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field
from selectolax.parser import HTMLParser

from app.engine.http import fetch

TYPE_HINT = re.compile(r"rss|atom", re.I)
XML_TYPES = {"application/xml", "text/xml", "application/rss+xml",
             "application/atom+xml"}
PATH_HINT = re.compile(
    r"(?:/feeds?\.xml$|/feed/?$|/rss(?:\.xml)?$|/atom\.xml$|"
    r"\.rss$|\.atom$|[?&]feed=)",
    re.I)
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}")


class FeedItem(BaseModel):
    title: str = ""
    url: str = ""
    published: str = ""
    source_feed: str = ""


class FeedIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    feeds: list[str] = Field(default_factory=list)
    items: list[FeedItem] = Field(default_factory=list)
    latest_published: str | None = None
    methodology: str = (
        "Feeds are taken from homepage rel=alternate / feed-looking links on "
        "the same host. Item dates are pubDate / published / updated only. "
        "Titles never supply a date. This is not traffic or engagement.")


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if "}" in tag else tag.lower()


def normalize_date(raw: str) -> str:
    """YYYY-MM-DD from a feed date field. Empty if the field is not a date."""
    text = (raw or "").strip()
    if not text:
        return ""
    if ISO_DAY.match(text):
        return text[:10]
    iso = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso).date().isoformat()
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError, IndexError):
        return ""
    if parsed is None:
        return ""
    return parsed.date().isoformat()


def discover_feed_urls(page_url: str, html: str) -> list[str]:
    """Same-host feed URLs the page itself advertised. Pure function."""
    host = _host(page_url)
    if not host or not html:
        return []
    tree = HTMLParser(html)
    out: list[str] = []

    def take(href: str, typ: str = "", *, path_ok: bool = False) -> None:
        href = (href or "").strip()
        if not href:
            return
        typ = (typ or "").lower()
        if typ and typ not in XML_TYPES and not TYPE_HINT.search(typ):
            return
        if not typ and not path_ok:
            return
        absolute = urljoin(page_url, href).split("#")[0]
        if _host(absolute) != host:
            return
        if absolute not in out:
            out.append(absolute)

    for node in tree.css("link[href]"):
        rel = (node.attributes.get("rel") or "").lower()
        if "alternate" not in rel and "feed" not in rel:
            continue
        take(node.attributes.get("href") or "", node.attributes.get("type") or "")
    for node in tree.css("a[href]"):
        href = node.attributes.get("href") or ""
        if PATH_HINT.search(href):
            take(href, path_ok=True)
    return out[:5]


def parse_feed(xml: str, feed_url: str, *, limit: int = 15) -> list[FeedItem]:
    """RSS 2.0 or Atom items. Malformed XML → empty list, no guessed items."""
    if not xml or "<" not in xml:
        return []
    try:
        root = ET.fromstring(xml.lstrip("\ufeff"))
    except ET.ParseError:
        return []
    items: list[FeedItem] = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        title = ""
        link = ""
        published = ""
        for child in list(el):
            name = _local(child.tag)
            text = (child.text or "").strip()
            if name == "title" and text:
                title = text
            elif name == "link":
                href = (child.attrib.get("href") or text).strip()
                rel = (child.attrib.get("rel") or "").lower()
                if href and rel != "enclosure" and (not link or rel in ("", "alternate")):
                    link = href
            elif name in ("pubdate", "published", "updated", "date") and text:
                if not published:
                    published = normalize_date(text)
            elif name == "guid" and not link:
                permalink = (child.attrib.get("isPermaLink") or "true").lower()
                if permalink != "false" and text.startswith("http"):
                    link = text
        if not title and not link:
            continue
        items.append(FeedItem(
            title=title[:200],
            url=link,
            published=published,
            source_feed=feed_url,
        ))
        if len(items) >= limit:
            break
    return items


def from_xml(xml: str, feed_url: str) -> FeedIntel:
    """Pure: one feed body → intel. Used by tests and the async collector."""
    items = parse_feed(xml, feed_url)
    dates = [i.published for i in items if i.published]
    return FeedIntel(
        assessed=True,
        feeds=[feed_url],
        items=items,
        latest_published=max(dates) if dates else None,
    )


async def analyse(page_url: str, html: str) -> FeedIntel:
    urls = discover_feed_urls(page_url, html)
    if not urls:
        return FeedIntel(
            assessed=False,
            reason="No RSS or Atom feed advertised on the homepage.",
        )
    items: list[FeedItem] = []
    fetched: list[str] = []
    parse_failed = 0
    for url in urls[:2]:
        resp = await fetch(url)
        if not resp.ok:
            continue
        fetched.append(url)
        parsed = parse_feed(resp.text, url)
        if not parsed and "<" in (resp.text or ""):
            parse_failed += 1
        items.extend(parsed)
    seen: set[str] = set()
    unique: list[FeedItem] = []
    for item in items:
        key = item.url or item.title
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique = unique[:15]
    if not fetched:
        return FeedIntel(
            assessed=False,
            feeds=urls,
            reason="Advertised feed URL(s) could not be fetched.",
        )
    if not unique and parse_failed:
        return FeedIntel(
            assessed=False,
            feeds=fetched,
            reason="Feed response was not well-formed RSS or Atom XML.",
        )
    dates = [i.published for i in unique if i.published]
    return FeedIntel(
        assessed=True,
        feeds=fetched,
        items=unique,
        latest_published=max(dates) if dates else None,
    )
