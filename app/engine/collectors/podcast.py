"""Podcast collector — iTunes lookup + the show's own RSS/Atom feed.

Apple's lookup publishes ``feedUrl`` and ``trackCount``. Episode titles and
dates come from that feed. Listen/download counts are not in RSS and are
not invented. Feed length is not total episodes.

Apple's customer-review RSS is official and keyless. Review bodies and
printed star ratings are copied. Review-feed length is not the store's total
review count. Ratings are not listen counts and are not follower counts.

A Spotify show URL has no public RSS. The surface is recorded; episodes stay
unavailable unless an Apple Podcasts id is present.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from dateutil import parser as dateparser

from app.engine.http import fetch
from app.schemas import ContentItem, PlatformAccount, Testimonial

_ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
_ATOM = "{http://www.w3.org/2005/Atom}"
_HTML = re.compile(r"<[^>]+>")
_RSS_NOTE = (
    "Recent episodes came from the show's public RSS/Atom feed advertised by "
    "Apple Podcasts. Feed length is not total episodes; listen counts are not "
    "in the feed."
)
_REVIEW_NOTE = (
    "Customer reviews came from Apple's public review RSS. "
    "Review-feed length is not the store's total review count. "
    "Star ratings are not listen counts."
)
_SPOTIFY_NOTE = (
    "Spotify show pages do not publish an RSS feed URL. Episode titles stay "
    "unavailable unless Apple Podcasts lists the same show."
)


def itunes_id_from(url: str) -> str:
    match = re.search(r"id(\d{6,})", url or "")
    return match.group(1) if match else ""


def spotify_show_id_from(url: str) -> str:
    match = re.search(r"open\.spotify\.com/show/([A-Za-z0-9]{22})", url or "")
    return match.group(1) if match else ""


def review_feed_url(ident: str) -> str:
    return ("https://itunes.apple.com/rss/customerreviews/"
            f"id={ident}/sortBy=mostRecent/json")


def parse_lookup(payload: dict) -> dict[str, Any]:
    """Copy iTunes lookup fields. trackCount is Apple's published episode count."""
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return {}
    row = rows[0]
    count = row.get("trackCount")
    rating = row.get("averageUserRating")
    rating_count = row.get("userRatingCount")
    return {
        "title": str(row.get("collectionName") or row.get("trackName") or "").strip(),
        "publisher": str(row.get("artistName") or "").strip(),
        "feed_url": str(row.get("feedUrl") or "").strip(),
        "description": str(row.get("description") or "").strip()[:800],
        "view_url": str(row.get("collectionViewUrl") or row.get("trackViewUrl") or "").strip(),
        "track_count": count if isinstance(count, int) and count > 0 else None,
        "apple_average_rating": (
            float(rating) if isinstance(rating, (int, float)) and rating > 0 else None
        ),
        "apple_rating_count": (
            rating_count if isinstance(rating_count, int) and rating_count > 0 else None
        ),
    }


def _label(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("label") or "").strip()
    return str(node or "").strip()


def _star(raw: str) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if 1 <= value <= 5:
        return value
    return None


def parse_reviews(payload: dict, *, limit: int = 12) -> list[dict[str, Any]]:
    """Copy Apple customer-review RSS rows. The software/show entry has no stars."""
    feed = payload.get("feed") if isinstance(payload, dict) else None
    if not isinstance(feed, dict):
        return []
    entries = feed.get("entry")
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        rating = _star(_label(entry.get("im:rating")))
        if rating is None:
            continue
        text = _HTML.sub(" ", _label(entry.get("content"))).strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        author = _label((entry.get("author") or {}).get("name")
                        if isinstance(entry.get("author"), dict) else "")
        updated = _label(entry.get("updated"))
        dated = updated[:10] if len(updated) >= 10 and updated[4] == "-" else None
        out.append({
            "text": text[:400],
            "author": author or None,
            "rating": rating,
            "dated": dated,
        })
        if len(out) >= limit:
            break
    return out


def _duration_seconds(raw: str) -> int | None:
    text = (raw or "").strip()
    if text.isdigit():
        amount = int(text)
        return amount if amount > 0 else None
    parts = text.split(":")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    secs = 0
    for part in parts:
        secs = secs * 60 + int(part)
    return secs or None


def parse_rss(xml_text: str) -> dict[str, Any]:
    """Copy show title and recent items. No listen counts."""
    out: dict[str, Any] = {"title": "", "description": "", "items": []}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    channel = root.find("channel")
    if channel is not None:
        out["title"] = (channel.findtext("title") or "").strip()
        out["description"] = (channel.findtext("description") or "").strip()
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            if not title:
                continue
            link = (item.findtext("link") or "").strip()
            published = (item.findtext("pubDate") or "").strip()
            duration = (item.findtext(f"{_ITUNES}duration")
                        or item.findtext("duration") or "")
            published_at = None
            if published:
                try:
                    published_at = dateparser.parse(published)
                except (ValueError, OverflowError, TypeError):
                    published_at = None
            out["items"].append({
                "title": title,
                "url": link or None,
                "published_at": published_at,
                "duration_seconds": _duration_seconds(duration),
            })
            if len(out["items"]) >= 8:
                break
        return out

    out["title"] = (root.findtext(f"{_ATOM}title") or "").strip()
    out["description"] = (root.findtext(f"{_ATOM}subtitle") or "").strip()
    for entry in root.findall(f"{_ATOM}entry"):
        title = (entry.findtext(f"{_ATOM}title") or "").strip()
        if not title:
            continue
        link_el = entry.find(f"{_ATOM}link")
        href = link_el.get("href") if link_el is not None else ""
        published = (entry.findtext(f"{_ATOM}published")
                     or entry.findtext(f"{_ATOM}updated") or "").strip()
        published_at = None
        if published:
            try:
                published_at = dateparser.parse(published)
            except (ValueError, OverflowError, TypeError):
                published_at = None
        out["items"].append({
            "title": title,
            "url": href or None,
            "published_at": published_at,
            "duration_seconds": None,
        })
        if len(out["items"]) >= 8:
            break
    return out


async def collect(url: str) -> PlatformAccount:
    ident = itunes_id_from(url)
    show = spotify_show_id_from(url)
    if ident:
        page = f"https://podcasts.apple.com/podcast/id{ident}"
        handle = ident
    elif show:
        page = f"https://open.spotify.com/show/{show}"
        handle = show
    elif (url or "").isdigit() and len(url) >= 6:
        ident = url
        page = f"https://podcasts.apple.com/podcast/id{ident}"
        handle = ident
    else:
        handle = url or ""
        page = url or ""
    acc = PlatformAccount(
        platform="podcast", handle=handle, url=page,
        raw={"source": "url_only"},
    )

    if show and not ident:
        acc.raw["source"] = "spotify_show_url"
        acc.errors.append(_SPOTIFY_NOTE)
        return acc
    if not ident:
        acc.errors.append("No Apple Podcasts id in this URL.")
        return acc

    lookup_resp = await fetch(
        f"https://itunes.apple.com/lookup?id={ident}&entity=podcast",
        check_robots=False,
    )
    meta: dict[str, Any] = {}
    if lookup_resp.ok:
        try:
            body = json.loads(lookup_resp.text)
        except json.JSONDecodeError:
            body = None
        meta = parse_lookup(body) if isinstance(body, dict) else {}
    if meta:
        acc.display_name = meta.get("title") or None
        acc.bio = meta.get("description") or None
        acc.posts = meta.get("track_count")
        acc.raw["source"] = "itunes_lookup_api"
        acc.raw["publisher"] = meta.get("publisher") or ""
        if meta.get("view_url"):
            acc.url = meta["view_url"]
        if acc.posts is not None:
            acc.raw["posts_source"] = "itunes_lookup_trackCount"
        if meta.get("apple_average_rating") is not None:
            acc.raw["apple_average_rating"] = meta["apple_average_rating"]
        if meta.get("apple_rating_count") is not None:
            acc.raw["apple_rating_count"] = meta["apple_rating_count"]
        if meta.get("apple_average_rating") is not None:
            count_bit = (
                f" from {meta['apple_rating_count']:,} ratings"
                if meta.get("apple_rating_count") else ""
            )
            acc.errors.append(
                f"Apple Podcasts published an average rating of "
                f"{meta['apple_average_rating']}{count_bit}. "
                "That is not a listen count or a follower count."
            )
    elif not lookup_resp.ok:
        acc.errors.append(f"iTunes lookup failed (status {lookup_resp.status})")

    feed_url = meta.get("feed_url") or ""
    if feed_url:
        acc.raw["feed_url"] = feed_url
        feed = await fetch(feed_url)
        if feed.ok:
            parsed = parse_rss(feed.text)
            if parsed.get("title") and not acc.display_name:
                acc.display_name = parsed["title"]
            if parsed.get("description") and not acc.bio:
                acc.bio = parsed["description"][:800]
            for row in parsed["items"]:
                acc.content.append(ContentItem(
                    platform="podcast",
                    title=row["title"],
                    url=row["url"],
                    published_at=row["published_at"],
                    duration_seconds=row["duration_seconds"],
                    kind="episode",
                    raw={"source": "podcast_rss"},
                ))
            if acc.content:
                acc.errors.append(_RSS_NOTE)
        elif feed.blocked_by_robots:
            acc.errors.append("The show's RSS feed is disallowed by robots.txt.")
        else:
            acc.errors.append(f"RSS fetch failed (status {feed.status})")
    elif meta:
        acc.errors.append("iTunes lookup had no feedUrl; episode list unavailable.")

    review_resp = await fetch(review_feed_url(ident), check_robots=False)
    if review_resp.ok:
        try:
            review_body = json.loads(review_resp.text)
        except json.JSONDecodeError:
            review_body = None
        reviews = parse_reviews(review_body) if isinstance(review_body, dict) else []
        for row in reviews:
            acc.testimonials.append(Testimonial(
                text=row["text"],
                author=row.get("author"),
                rating=row.get("rating"),
                dated=row.get("dated"),
            ))
        if reviews:
            acc.errors.append(_REVIEW_NOTE)
    return acc
