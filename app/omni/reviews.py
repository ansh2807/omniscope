"""Review intelligence from on-page structured data only (spec §16).

Themes are keyword buckets on review bodies the site itself published.
Star ratings without text are recorded as printed aggregates, not sentiment.
Third-party review platforms are not scraped. A missing AggregateRating is
empty schema, not 'they have no reviews'.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.engine.collectors.web import _jsonld

THEMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pricing", ("price", "pricing", "expensive", "cheap", "cost", "overpriced",
                 "value", "subscription")),
    ("ux", ("ux", "ui", "usability", "confusing", "intuitive", "interface",
            "design", "navigation")),
    ("support", ("support", "customer service", "help desk", "response",
                 "onboarding")),
    ("performance", ("slow", "fast", "performance", "latency", "speed", "lag")),
    ("reliability", ("bug", "crash", "outage", "reliable", "stable", "broke")),
    ("features", ("feature", "missing", "wishlist", "cannot", "doesn't support")),
)
ORG_TYPES = {"Organization", "LocalBusiness", "OnlineBusiness", "Corporation"}


class ReviewItem(BaseModel):
    body: str
    author: str = ""
    rating: float | None = None
    published: str = ""
    source_url: str = ""
    themes: list[str] = Field(default_factory=list)


class RatingCard(BaseModel):
    name: str = ""
    value: str = ""
    count: str = ""
    best: str = ""
    via: str = ""
    url: str = ""


class ReviewIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    item_count: int = 0
    aggregate_rating: float | None = None
    aggregate_count: int | None = None
    ratings: list[RatingCard] = Field(default_factory=list)
    items: list[ReviewItem] = Field(default_factory=list)
    themes: dict[str, int] = Field(default_factory=dict)
    methodology: str = (
        "Reviews are JSON-LD Review objects and printed AggregateRating on "
        "sampled pages (Organization, LocalBusiness, Product, or standalone). "
        "Theme labels are keyword matches on the review body. ratingValue and "
        "reviewCount are printed fields, not a verified review volume or "
        "transaction count. Body copy such as '4.9 stars' is ignored. This is "
        "not G2/Capterra collection and not a sentiment model.")


def classify_themes(text: str) -> list[str]:
    blob = (text or "").lower()
    hit = []
    for name, words in THEMES:
        if any(re.search(rf"\b{re.escape(w)}\b", blob) for w in words):
            hit.append(name)
    return hit


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _type_names(entity: dict) -> list[str]:
    raw = entity.get("@type")
    if isinstance(raw, str):
        return [raw.split("/")[-1]]
    names: list[str] = []
    for item in raw or []:
        if isinstance(item, str):
            names.append(item.split("/")[-1])
    return names


def _as_types(entity: dict) -> set[str]:
    return set(_type_names(entity))


def _printed_number(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        text = str(value).strip()
        return text[:-2] if text.endswith(".0") else text
    if isinstance(value, str):
        return value.strip()[:40]
    if isinstance(value, dict):
        return _printed_number(
            value.get("ratingValue") or value.get("value") or value.get("name"))
    return ""


def _rating_value(node: Any) -> float | None:
    if isinstance(node, dict):
        node = node.get("ratingValue")
    try:
        return float(str(node).replace(",", "")) if node is not None else None
    except ValueError:
        return None


def _text_name(entity: dict) -> str:
    raw = entity.get("name") or entity.get("headline")
    if isinstance(raw, str):
        return raw.strip()[:160]
    if isinstance(raw, dict):
        nested = raw.get("name")
        if isinstance(nested, str):
            return nested.strip()[:160]
    return ""


def extract_ratings(entities: list[dict], page_url: str) -> list[RatingCard]:
    """Printed AggregateRating nodes. Body star copy is ignored."""
    out: list[RatingCard] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(node: dict, via: str, parent_name: str) -> None:
        if not isinstance(node, dict):
            return
        value = _printed_number(node.get("ratingValue"))
        count = _printed_number(node.get("ratingCount") or node.get("reviewCount"))
        best = _printed_number(node.get("bestRating"))
        if not (value or count):
            return
        name = _text_name(node) or parent_name
        key = (via.lower(), name.lower(), value, count)
        if key in seen:
            return
        seen.add(key)
        href = node.get("url")
        out.append(RatingCard(
            name=name[:160],
            value=value,
            count=count,
            best=best,
            via=via[:80],
            url=href if isinstance(href, str) and href.startswith("http") else page_url,
        ))

    for entity in entities:
        types = _as_types(entity)
        parent = _text_name(entity)
        if "AggregateRating" in types:
            add(entity, "AggregateRating", parent)
        via = next((name for name in (
            "LocalBusiness", "Organization", "OnlineBusiness", "Corporation",
            "Product", "Course", "Service", "Brand", "SoftwareApplication")
            if name in types), "")
        for node in _as_list(entity.get("aggregateRating")):
            if isinstance(node, dict):
                add(node, via or "schema", parent)
    return out[:12]


def _pick_aggregate(cards: list[RatingCard]) -> tuple[float | None, int | None]:
    """One printed card. Never averages two schema nodes into a site score."""
    if not cards:
        return None, None
    preferred = next((card for card in cards if card.via in ORG_TYPES), cards[0])
    rating = None
    count = None
    try:
        if preferred.value:
            rating = float(preferred.value.replace(",", ""))
    except ValueError:
        rating = None
    try:
        if preferred.count:
            count = int(float(str(preferred.count).replace(",", "")))
    except ValueError:
        count = None
    return rating, count


def extract_reviews(entities: list[dict], page_url: str) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for entity in entities:
        if "Review" not in _as_types(entity):
            continue
        body = str(entity.get("reviewBody") or entity.get("description") or "").strip()
        if not body:
            continue
        author = entity.get("author")
        if isinstance(author, dict):
            author = author.get("name") or ""
        published = entity.get("datePublished")
        if not isinstance(published, str):
            published = ""
        items.append(ReviewItem(
            body=body[:500],
            author=str(author or "")[:80],
            rating=_rating_value(entity.get("reviewRating")),
            published=published[:10],
            source_url=page_url,
            themes=classify_themes(body),
        ))
    return items


def analyse_reviews(raw_html: list[tuple[str, str]],
                    products: list[dict] | None = None) -> ReviewIntel:
    """Pure function over fetched HTML + already-extracted product rows."""
    items: list[ReviewItem] = []
    cards: list[RatingCard] = []
    seen_card: set[tuple[str, str, str, str]] = set()
    for url, html in raw_html:
        entities = [e for e in _jsonld(html or "") if isinstance(e, dict)]
        items.extend(extract_reviews(entities, url))
        for card in extract_ratings(entities, url):
            key = (card.via.lower(), card.name.lower(), card.value, card.count)
            if key in seen_card:
                continue
            seen_card.add(key)
            cards.append(card)

    agg, agg_n = _pick_aggregate(cards)
    if agg is None:
        ratings = [float(p["rating"]) for p in (products or [])
                   if p.get("rating") is not None]
        counts = []
        for p in (products or []):
            try:
                if p.get("rating_count") is not None:
                    counts.append(int(p["rating_count"]))
            except (TypeError, ValueError):
                continue
        agg = round(sum(ratings) / len(ratings), 2) if ratings else None
        agg_n = max(counts) if counts else (len(ratings) if ratings else None)

    if not items and not cards and agg is None:
        return ReviewIntel(
            assessed=False,
            reason="No JSON-LD Review objects or aggregateRating on sampled pages. "
                   "Reviews may live on third-party platforms this engine does not fetch.",
        )
    themes: dict[str, int] = {}
    for item in items:
        for theme in item.themes:
            themes[theme] = themes.get(theme, 0) + 1
    reason = ""
    if items:
        reason = ""
    elif cards or agg is not None:
        reason = ("Only aggregate star ratings were published — "
                  "no review bodies to theme.")
    return ReviewIntel(
        assessed=True,
        item_count=len(items),
        aggregate_rating=agg,
        aggregate_count=agg_n,
        ratings=cards[:12],
        items=items[:20],
        themes=themes,
        reason=reason,
    )
