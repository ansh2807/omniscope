"""Generic web collectors: websites, Topmate, SuperProfile, Linktree, Telegram, app stores.

Everything here goes through the robots-respecting client. Topmate and the link-in-bio
services are where the actual commercial intelligence lives — price ladders, product
names, testimonials — and they are all fully public pages.

When Instagram hides a grid, the official website's advertised RSS/Atom and
Telegram's own t.me/s preview still publish titles and dates. Those are copied.
Feed or preview length is never treated as a lifetime post count. Traffic is
never invented. Conventional /rss.xml is never probed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

from app.config import settings
from app.engine.http import fetch
from app.engine.numbers import parse_human_count
from app.omni import feeds as site_feeds
from app.schemas import ContentItem, PlatformAccount, Product, Testimonial

_SITE_FEED_NOTE = (
    "Advertised RSS/Atom items copied from the official site. "
    "Feed length is not the site's total post count. No traffic is implied."
)
_TG_NOTE = (
    "Public channel preview messages copied from t.me/s. "
    "Preview length is not the channel's total post count."
)

RUPEE = re.compile(r"₹\s?([\d,]+(?:\.\d+)?)")
COMMERCE = re.compile(
    r"\b(course|program|programme|workshop|masterclass|mentorship|consultation|session|"
    r"coaching|cohort|membership|book|ebook|buy|enrol|enroll|register|checkout|price|"
    r"fee|fees|sale|offer|package|bootcamp)\b", re.I)


def _text(html: str) -> str:
    tree = HTMLParser(html)
    for tag in tree.css("script, style, noscript, svg"):
        tag.decompose()
    body = tree.body or tree
    return re.sub(r"\n{3,}", "\n\n", body.text(separator="\n", strip=True))


def _meta(html: str, prop: str) -> str | None:
    m = re.search(rf'<meta\s+(?:property|name)="{prop}"\s+content="([^"]*)"', html, re.I)
    return m.group(1) if m else None


def _price(s: str) -> float | None:
    m = RUPEE.search(s)
    return float(m.group(1).replace(",", "")) if m else None


def _commercial_price_line(value: str) -> bool:
    """Visible currency becomes an offer only when nearby language is commercial."""
    return bool(RUPEE.search(value or "") and COMMERCE.search(value or ""))


def _jsonld(html: str) -> list[dict]:
    """Return flattened JSON-LD entities, including objects nested in @graph."""
    tree = HTMLParser(html)
    entities: list[dict] = []

    def add(value) -> None:
        if isinstance(value, list):
            for item in value:
                add(item)
        elif isinstance(value, dict):
            entities.append(value)
            if "@graph" in value:
                add(value["@graph"])

    for node in tree.css('script[type="application/ld+json"]'):
        try:
            add(json.loads(node.text()))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return entities


def _structured_products(entities: list[dict], page_url: str) -> list[Product]:
    products: list[Product] = []
    for entity in entities:
        types = entity.get("@type", [])
        types = {types} if isinstance(types, str) else set(types or [])
        if not ({"Product", "Course", "Service"} & types):
            continue
        offers = entity.get("offers") or {}
        offers = offers if isinstance(offers, list) else [offers]
        for offer in offers or [{}]:
            if not isinstance(offer, dict):
                continue
            raw_price = offer.get("price") or offer.get("lowPrice")
            try:
                price = float(str(raw_price).replace(",", "")) if raw_price is not None else None
            except ValueError:
                price = None
            currency = str(offer.get("priceCurrency") or "INR").upper()
            # Product.price_inr must never silently label USD/EUR as rupees.
            price_inr = price if currency in {"INR", "RS", "₹"} else None
            products.append(Product(
                name=str(entity.get("name") or offer.get("name") or "Unnamed offer")[:150],
                price_inr=price_inr,
                kind=("course" if "Course" in types else
                      "service" if "Service" in types else "product"),
                url=offer.get("url") or entity.get("url") or page_url,
                rating=(entity.get("aggregateRating") or {}).get("ratingValue")
                if isinstance(entity.get("aggregateRating"), dict) else None,
                rating_count=(entity.get("aggregateRating") or {}).get("ratingCount")
                if isinstance(entity.get("aggregateRating"), dict) else None,
            ))
    return products


def _same_as(entities: list[dict]) -> list[str]:
    out: list[str] = []
    for entity in entities:
        values = entity.get("sameAs") or []
        values = [values] if isinstance(values, str) else values
        for value in values:
            if isinstance(value, str) and value.startswith("http") and value not in out:
                out.append(value)
    return out


RELEVANT_PAGE = re.compile(
    r"/(about|bio|products?|courses?|programs?|services?|offers?|shop|store|pricing|"
    r"mentorship|consult|book|contact)(?:[/_.-]|$)", re.I)


def day_from_iso(value: str) -> datetime | None:
    """Parse a feed or Telegram datetime. Empty or non-dates stay None."""
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def content_from_feed_items(items) -> list[ContentItem]:
    """Copy advertised feed rows. Titles never supply a date. No views."""
    out: list[ContentItem] = []
    for item in items or []:
        title = (getattr(item, "title", None) or "").strip()
        if not title:
            continue
        url = (getattr(item, "url", None) or "").strip() or None
        feed = (getattr(item, "source_feed", None) or "").strip()
        out.append(ContentItem(
            platform="website",
            title=title[:200],
            url=url,
            published_at=day_from_iso(getattr(item, "published", None) or ""),
            kind="post",
            raw={"source": "advertised_rss_atom", "feed": feed},
        ))
    return out


def parse_telegram_preview(html: str, *, limit: int = 15) -> list[dict]:
    """Messages Telegram printed on t.me/s. Image-only rows are skipped."""
    if not html:
        return []
    tree = HTMLParser(html)
    out: list[dict] = []
    for node in tree.css(".tgme_widget_message"):
        text_el = node.css_first(".tgme_widget_message_text")
        title = (text_el.text(separator=" ", strip=True) if text_el else "").strip()
        if not title:
            continue
        href = ""
        date_el = node.css_first("a.tgme_widget_message_date")
        if date_el:
            href = (date_el.attributes.get("href") or "").strip()
        if not href:
            data_post = (node.attributes.get("data-post") or "").strip()
            if data_post:
                href = f"https://t.me/{data_post}"
        published = None
        time_el = node.css_first("time[datetime]")
        if time_el:
            published = day_from_iso(time_el.attributes.get("datetime") or "")
        views = None
        views_el = node.css_first(".tgme_widget_message_views")
        if views_el:
            views = parse_human_count(views_el.text())
        row: dict = {"title": title[:200], "url": href or None,
                     "published_at": published}
        if views is not None:
            row["views"] = views
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _attach_site_feeds(acc: PlatformAccount, intel) -> None:
    items = content_from_feed_items(getattr(intel, "items", None))
    feeds = list(getattr(intel, "feeds", None) or [])
    if items:
        acc.content.extend(items)
        acc.raw["feeds"] = feeds
        acc.errors.append(_SITE_FEED_NOTE)
        return
    if feeds:
        acc.raw["feeds"] = feeds
        reason = (getattr(intel, "reason", None) or "").strip()
        if reason:
            acc.errors.append(reason)


# ------------------------------------------------------------------- websites
async def collect_website(url: str) -> PlatformAccount:
    acc = PlatformAccount(platform="website", url=url, raw={"source": "public_web"})
    r = await fetch(url)
    if r.blocked_by_robots:
        acc.errors.append("skipped: disallowed by robots.txt")
        return acc
    if not r.ok:
        acc.errors.append(f"fetch failed (status {r.status})")
        return acc

    acc.display_name = _meta(r.text, "og:site_name") or _meta(r.text, "og:title")
    acc.bio = _meta(r.text, "description") or _meta(r.text, "og:description")
    page_url = getattr(r, "final_url", None) or url
    host = urlparse(page_url).netloc.lower()

    root_tree = HTMLParser(r.text)
    candidates: list[str] = []
    for a in root_tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        absolute = urljoin(url, href).split("#")[0]
        if urlparse(absolute).netloc.lower() == host and RELEVANT_PAGE.search(urlparse(absolute).path):
            if absolute.rstrip("/") != url.rstrip("/") and absolute not in candidates:
                candidates.append(absolute)
    intel, responses = await asyncio.gather(
        site_feeds.analyse(page_url, r.text),
        asyncio.gather(
            *(fetch(x) for x in candidates[:max(0, settings.website_max_pages - 1)]),
            return_exceptions=True,
        ),
    )
    _attach_site_feeds(acc, intel)
    pages = [(url, r)] + [(u, page) for u, page in zip(candidates, responses)
                          if not isinstance(page, Exception) and page.ok]

    excerpts: list[str] = []
    structured_entities: list[dict] = []
    page_log: list[dict] = []
    for page_url, page in pages:
        body = _text(page.text)
        excerpts.append(body[:6000])
        entities = _jsonld(page.text)
        structured_entities.extend(entities)
        page_log.append({
            "url": getattr(page, "final_url", None) or page_url,
            "fetched_at": getattr(page, "fetched_at", None),
            "from_cache": bool(getattr(page, "from_cache", False)),
            "content_sha256": getattr(page, "content_sha256", None) or
                              hashlib.sha256(page.text.encode()).hexdigest(),
        })
        tree = HTMLParser(page.text)
        for a in tree.css("a[href]"):
            href = (a.attributes.get("href") or "").strip()
            if href.startswith(("mailto:", "tel:", "#", "javascript:")):
                continue
            absolute = urljoin(page_url, href)
            if urlparse(absolute).netloc and urlparse(absolute).netloc.lower() != host:
                if absolute not in acc.external_links:
                    acc.external_links.append(absolute)
        acc.external_links.extend(x for x in _same_as(entities) if x not in acc.external_links)
        acc.products.extend(_structured_products(entities, page_url))

        # Visible currency text is a fallback when the page publishes no Product schema.
        for line in body.splitlines():
            p = _price(line)
            if p and 50 <= p <= 500_000 and _commercial_price_line(line):
                label = RUPEE.sub("", line).strip(" -–—|·")[:90]
                if label and len(label) > 3:
                    acc.products.append(Product(name=label, price_inr=p, kind="course",
                                                url=page_url))

    # Deduplicate without hiding divergent prices; the corroborator needs both values.
    seen, products = set(), []
    for product in acc.products:
        key = (_norm_product(product.name), product.price_inr, product.url)
        if key not in seen:
            seen.add(key)
            products.append(product)
    acc.products = products[:50]
    acc.external_links = list(dict.fromkeys(acc.external_links))[:80]
    acc.raw.update({
        "text_excerpt": "\n\n".join(excerpts)[:18000],
        "pages_collected": page_log,
        "structured_entities": [
            {"type": e.get("@type"), "name": e.get("name"), "url": e.get("url")}
            for e in structured_entities[:100]
        ],
        "crawl_scope": f"same-host public pages, max {settings.website_max_pages}",
    })
    return acc


def _norm_product(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


# -------------------------------------------------------------------- topmate
async def collect_topmate(handle: str) -> PlatformAccount:
    url = f"https://topmate.io/{handle}"
    acc = PlatformAccount(platform="topmate", handle=handle, url=url,
                          raw={"source": "public_profile"})
    r = await fetch(url)
    if not r.ok:
        acc.errors.append(f"fetch failed (status {r.status})")
        return acc

    acc.display_name = _meta(r.text, "og:title")
    acc.bio = _meta(r.text, "og:description")
    body = _text(r.text)
    lines = [l.strip() for l in body.splitlines() if l.strip()]

    # Product cards render as: <title line> ... ₹<price>
    for i, line in enumerate(lines):
        p = _price(line)
        if not p:
            continue
        name = ""
        for back in range(1, 5):
            if i - back < 0:
                break
            cand = lines[i - back]
            if _price(cand) or cand.lower().startswith(("video meeting", "priority dm", "package", "popular", "best deal")):
                continue
            if 3 < len(cand) < 90:
                name = cand
                break
        kind = "package" if "package" in body[max(0, i - 200):i].lower() else "service"
        acc.products.append(Product(name=name or "Unnamed offer", price_inr=p, kind=kind, url=url))

    # dedupe by (name, price), keep order
    seen, uniq = set(), []
    for p in acc.products:
        k = (p.name, p.price_inr)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)
    acc.products = uniq

    m = re.search(r"([\d,]+)\s+ratings?", body, re.I)
    if m:
        acc.raw["rating_count"] = int(m.group(1).replace(",", ""))
    m = re.search(r"(\d(?:\.\d)?)\s*/\s*5", body)
    if m:
        acc.raw["rating"] = float(m.group(1))

    # Testimonials sit between a "5/5" marker and the reviewer name.
    for block in re.split(r"\n5/5\n", body)[1:]:
        chunk = [l for l in block.splitlines() if l.strip()][:3]
        if not chunk:
            continue
        text = chunk[0]
        if len(text) < 25:
            continue
        author = chunk[1] if len(chunk) > 1 and len(chunk[1]) < 40 else None
        dated = chunk[2] if len(chunk) > 2 and re.search(r"\d{4}", chunk[2]) else None
        acc.testimonials.append(Testimonial(text=text[:400], author=author, rating=5.0, dated=dated))
    acc.testimonials = acc.testimonials[:40]
    return acc


# ----------------------------------------------------------------- link-in-bio
async def collect_linkinbio(url: str) -> PlatformAccount:
    """Linktree / SuperProfile / Beacons / Canva sites — the creator's own funnel map."""
    platform = ("linktree" if "linktr.ee" in url
                else "superprofile" if "superprofile" in url else "website")
    acc = PlatformAccount(platform=platform, url=url, raw={"source": "link_in_bio"})
    r = await fetch(url)
    if not r.ok:
        acc.errors.append(f"fetch failed (status {r.status})")
        return acc

    acc.display_name = _meta(r.text, "og:title")
    acc.bio = _meta(r.text, "og:description")
    tree = HTMLParser(r.text)
    profile_host = urlparse(url).netloc.lower().replace("www.", "")
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href.startswith("http"):
            continue
        if any(s in href for s in ("linktr.ee/s/", "/privacy", "/cookie", "/report",
                                   "linktree.com", "/about", "/explore")):
            continue
        # Linktree/Beacons footer and editorial links belong to the platform, not the
        # creator. Creator destinations must leave the link-page host.
        href_host = urlparse(href).netloc.lower().replace("www.", "")
        if href_host == profile_host:
            continue
        if href not in acc.external_links:
            acc.external_links.append(href)
    acc.external_links = acc.external_links[:40]

    body = _text(r.text)
    for line in body.splitlines():
        p = _price(line)
        if p and 50 <= p <= 500_000:
            acc.products.append(Product(name=RUPEE.sub("", line).strip()[:90],
                                        price_inr=p, kind="course", url=url))
    acc.products = acc.products[:20]
    return acc


# -------------------------------------------------------------------- telegram
async def collect_telegram(handle: str) -> PlatformAccount:
    """t.me/s/<channel> is Telegram's own public web preview. No auth involved."""
    url = f"https://t.me/s/{handle}"
    acc = PlatformAccount(platform="telegram", handle=handle, url=url,
                          raw={"source": "public_channel_preview"})
    r = await fetch(url, check_robots=False)
    if not r.ok:
        acc.errors.append(f"fetch failed (status {r.status})")
        return acc
    acc.display_name = _meta(r.text, "og:title")
    acc.bio = _meta(r.text, "og:description")
    m = re.search(r"([\d\s,]+)\s+(?:subscribers|members)", _text(r.text), re.I)
    if m:
        acc.followers = int(re.sub(r"[^\d]", "", m.group(1)) or 0) or None
    for row in parse_telegram_preview(r.text):
        acc.content.append(ContentItem(
            platform="telegram",
            title=row["title"],
            url=row.get("url"),
            views=row.get("views"),
            published_at=row.get("published_at"),
            kind="post",
            raw={"source": "telegram_public_preview"},
        ))
    if acc.content:
        acc.errors.append(_TG_NOTE)
    return acc


# ------------------------------------------------------------------ app stores
async def collect_appstore(app_id: str) -> PlatformAccount:
    url = f"https://itunes.apple.com/lookup?id={app_id}"
    acc = PlatformAccount(platform="appstore", handle=app_id,
                          url=f"https://apps.apple.com/app/id{app_id}",
                          raw={"source": "itunes_lookup_api"})
    r = await fetch(url, check_robots=False)
    if not r.ok:
        acc.errors.append("lookup failed")
        return acc
    import json as _json
    try:
        results = _json.loads(r.text).get("results") or []
    except Exception:
        acc.errors.append("lookup returned non-JSON")
        return acc
    if not results:
        acc.errors.append("app not found")
        return acc
    d = results[0]
    acc.display_name = d.get("trackName")
    acc.bio = (d.get("description") or "")[:2000]
    acc.raw.update({
        "rating": d.get("averageUserRating"),
        "rating_count": d.get("userRatingCount"),
        "seller": d.get("sellerName"),
        "genres": d.get("genres"),
        "price": d.get("price"),
    })
    acc.products.append(Product(
        name=d.get("trackName", "App"), kind="app",
        price_inr=None if not d.get("price") else float(d["price"]),
        url=d.get("trackViewUrl"), rating=d.get("averageUserRating"),
        rating_count=d.get("userRatingCount"),
    ))
    return acc
