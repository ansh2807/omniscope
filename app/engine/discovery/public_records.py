"""Hydrate official public records for IDs we already have.

ORCID, Wikimedia pageviews, MusicBrainz and Spotify oEmbed are documented
public endpoints. They run only when Wikidata (or Wikipedia) already printed
the identifier. Nothing here is guessed from an Instagram handle.

Honesty:
  * ORCID works are not a product catalog.
  * ORCID employment is not an audience job.
  * Wikipedia pageviews are not site traffic or social followers.
  * MusicBrainz country is not a current base.
  * Spotify oEmbed title is not monthly listeners. Thumbnail is not a portrait.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from app.engine.http import fetch

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
MBID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
SPOTIFY_ARTIST_RE = re.compile(
    r"open\.spotify\.com/artist/([A-Za-z0-9]{22})",
    re.I,
)


def musicbrainz_id(value: str) -> str:
    """MusicBrainz artist MBID from a bare UUID or musicbrainz.org URL."""
    text = (value or "").strip()
    if not text:
        return ""
    if "musicbrainz.org/" in text.lower():
        text = text.rstrip("/").rsplit("/", 1)[-1]
    return text if MBID_RE.fullmatch(text) else ""


def spotify_artist_id(value: str) -> str:
    """Artist id from an open.spotify.com/artist URL. Shows stay empty."""
    match = SPOTIFY_ARTIST_RE.search(value or "")
    return match.group(1) if match else ""


def _load(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _text(node: Any) -> str:
    if isinstance(node, str):
        return node.strip()
    if isinstance(node, dict):
        for key in ("value", "content", "name"):
            found = _text(node.get(key))
            if found:
                return found
    return ""


def parse_orcid(payload: dict) -> dict[str, Any]:
    """Copy public ORCID person + affiliation + work titles. No citation counts."""
    if not isinstance(payload, dict):
        return {}
    person = payload.get("person") or {}
    name = person.get("name") or {}
    given = _text((name.get("given-names") or {}) if isinstance(name, dict) else "")
    family = _text((name.get("family-name") or {}) if isinstance(name, dict) else "")
    display = " ".join(part for part in (given, family) if part)
    bio = ""
    biography = person.get("biography") or {}
    if isinstance(biography, dict):
        bio = _text(biography.get("content"))

    activities = payload.get("activities-summary") or {}
    employments = _orcid_affiliations(activities.get("employments"), "employment-summary")
    educations = _orcid_affiliations(activities.get("educations"), "education-summary")
    works = _orcid_works(activities.get("works"))
    if not (display or bio or employments or educations or works):
        return {}
    return {
        "display_name": display,
        "biography": bio[:400],
        "employments": employments[:6],
        "educations": educations[:6],
        "works": works[:8],
    }


def _orcid_affiliations(block: Any, summary_key: str) -> list[str]:
    if not isinstance(block, dict):
        return []
    out: list[str] = []
    for group in block.get("affiliation-group") or []:
        if not isinstance(group, dict):
            continue
        for row in group.get("summaries") or []:
            if not isinstance(row, dict):
                continue
            summary = row.get(summary_key) or {}
            if not isinstance(summary, dict):
                continue
            org = _text((summary.get("organization") or {}).get("name")
                        if isinstance(summary.get("organization"), dict) else "")
            role = _text(summary.get("role-title"))
            if org and role:
                label = f"{role} at {org}"
            else:
                label = org or role
            if label and label not in out:
                out.append(label)
    return out


def _orcid_works(block: Any) -> list[str]:
    if not isinstance(block, dict):
        return []
    out: list[str] = []
    for group in block.get("group") or []:
        if not isinstance(group, dict):
            continue
        for summary in group.get("work-summary") or []:
            if not isinstance(summary, dict):
                continue
            title_block = summary.get("title") or {}
            title = ""
            if isinstance(title_block, dict):
                title = _text((title_block.get("title") or {}).get("value")
                              if isinstance(title_block.get("title"), dict)
                              else title_block.get("title"))
            if title and title not in out:
                out.append(title)
    return out


def parse_pageviews(payload: dict) -> dict[str, Any]:
    """Sum daily Wikipedia article views. Not traffic and not followers."""
    if not isinstance(payload, dict):
        return {}
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return {}
    total = 0
    latest = 0
    days = 0
    article = ""
    for row in items:
        if not isinstance(row, dict):
            continue
        try:
            views = int(row.get("views"))
        except (TypeError, ValueError):
            continue
        if views < 0:
            continue
        total += views
        latest = views
        days += 1
        article = str(row.get("article") or article)
    if days <= 0:
        return {}
    return {
        "article": article.replace("_", " "),
        "days": days,
        "views": total,
        "latest_day": latest,
    }


def parse_musicbrainz(payload: dict) -> dict[str, Any]:
    """Artist name, type and official homepage. No listener counts."""
    if not isinstance(payload, dict):
        return {}
    name = _text(payload.get("name"))
    kind = _text(payload.get("type"))
    country = _text(payload.get("country"))
    disambiguation = _text(payload.get("disambiguation"))
    homepage = ""
    for rel in payload.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        if (rel.get("type") or "").lower() != "official homepage":
            continue
        url = rel.get("url") or {}
        resource = _text(url.get("resource") if isinstance(url, dict) else url)
        if resource.startswith("http"):
            homepage = resource
            break
    if not name:
        return {}
    return {
        "name": name,
        "type": kind,
        "country": country,
        "disambiguation": disambiguation,
        "homepage": homepage,
    }


def parse_spotify_oembed(payload: dict) -> dict[str, Any]:
    """Title only. Thumbnail is recorded but never used as a portrait."""
    if not isinstance(payload, dict):
        return {}
    title = _text(payload.get("title"))
    if not title:
        return {}
    return {
        "title": title,
        "thumbnail": _text(payload.get("thumbnail_url")),
    }


async def fetch_orcid(orcid: str) -> dict[str, Any]:
    ident = (orcid or "").strip()
    if not ORCID_RE.fullmatch(ident):
        return {}
    page = await fetch(
        f"https://pub.orcid.org/v3.0/{ident}/record",
        headers={"Accept": "application/json"},
    )
    if not page.ok:
        return {}
    payload = _load(page.text)
    return parse_orcid(payload) if isinstance(payload, dict) else {}


def pageviews_url(title: str, *, days: int = 30,
                  now: datetime | None = None) -> str:
    article = (title or "").strip().replace(" ", "_")
    if not article:
        return ""
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(days=max(days, 1))
    return (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        f"en.wikipedia/all-access/all-agents/{quote(article, safe='')}/daily/"
        f"{start.strftime('%Y%m%d')}/{end.strftime('%Y%m%d')}"
    )


async def fetch_pageviews(title: str) -> dict[str, Any]:
    url = pageviews_url(title)
    if not url:
        return {}
    page = await fetch(url, headers={"Accept": "application/json"})
    if not page.ok:
        return {}
    payload = _load(page.text)
    parsed = parse_pageviews(payload) if isinstance(payload, dict) else {}
    if parsed and not parsed.get("article"):
        parsed["article"] = title
    return parsed


async def fetch_musicbrainz(mbid: str) -> dict[str, Any]:
    ident = musicbrainz_id(mbid)
    if not ident:
        return {}
    page = await fetch(
        f"https://musicbrainz.org/ws/2/artist/{ident}?inc=url-rels&fmt=json",
        headers={"Accept": "application/json"},
    )
    if not page.ok:
        return {}
    payload = _load(page.text)
    return parse_musicbrainz(payload) if isinstance(payload, dict) else {}


async def fetch_spotify_artist(url: str) -> dict[str, Any]:
    artist = spotify_artist_id(url)
    if not artist:
        return {}
    page = await fetch(
        "https://open.spotify.com/oembed?url="
        + quote(f"https://open.spotify.com/artist/{artist}", safe=""),
        headers={"Accept": "application/json"},
    )
    if not page.ok:
        return {}
    payload = _load(page.text)
    return parse_spotify_oembed(payload) if isinstance(payload, dict) else {}
