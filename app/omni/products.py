"""Product intelligence — battlecards from what the site itself publishes.

Only structured Product/Course/Service offers and pricing-page signals are used.
Search demand, win rates and private SKUs stay UNAVAILABLE.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.engine.collectors.web import RUPEE, _commercial_price_line, _jsonld, _text


class OfferRow(BaseModel):
    name: str
    kind: str = "product"
    price_inr: float | None = None
    rating: float | None = None
    rating_count: int | None = None
    url: str | None = None
    availability: str = ""
    valid_until: str = ""


class ProductIntel(BaseModel):
    assessed: bool = False
    reason_not_assessed: str = ""
    pricing_model: str = "unpublished"   # free | paid | mixed | unpublished
    offer_count: int = 0
    price_floor: float | None = None
    price_ceiling: float | None = None
    ladder: list[OfferRow] = Field(default_factory=list)
    positioning: str = ""
    gaps: list[str] = Field(default_factory=list)
    visible_prices: list[dict] = Field(default_factory=list)
    policies: list[dict] = Field(default_factory=list)
    catalog: list[dict] = Field(default_factory=list)
    methodology: str = (
        "Offers are taken from JSON-LD Product/Course/Service schema on sampled "
        "pages. Visible ₹ lines near commercial words are listed separately and "
        "are not turned into SKUs. Availability and priceValidUntil are copied "
        "from Offer schema when printed. Return days and shipping destinations "
        "are copied from hasMerchantReturnPolicy / shippingDetails when printed. "
        "They are not a delivery-time model. sku / gtin / mpn / brand are copied "
        "from Product schema only — visible ₹ lines are never turned into SKUs. "
        "Non-INR prices are dropped, not converted.")


def visible_rupee_prices(raw_html: list[tuple[str, str]]) -> list[dict]:
    """On-page ₹ amounts next to commercial words. Not a SKU ladder."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for url, html in raw_html or []:
        for line in _text(html or "").splitlines():
            line = " ".join(line.split())
            if not _commercial_price_line(line):
                continue
            match = RUPEE.search(line)
            if not match:
                continue
            amount = match.group(1)
            key = (amount, url)
            if key in seen:
                continue
            seen.add(key)
            try:
                value = float(amount.replace(",", ""))
            except ValueError:
                continue
            out.append({
                "amount": value,
                "excerpt": line[:160],
                "url": url,
            })
            if len(out) >= 12:
                return out
    return out


def _schema_token(value: Any) -> str:
    if isinstance(value, str):
        return value.split("/")[-1].strip()
    if isinstance(value, dict):
        return _schema_token(value.get("@type") or value.get("name") or value.get("@id"))
    return ""


def offer_terms(raw_html: list[tuple[str, str]]) -> dict[str, dict]:
    """availability / priceValidUntil keyed by offer name. Pure."""
    out: dict[str, dict] = {}
    for url, html in raw_html or []:
        for entity in _jsonld(html or ""):
            if not isinstance(entity, dict):
                continue
            types = entity.get("@type")
            names = {types} if isinstance(types, str) else set(types or [])
            names = {str(n).split("/")[-1] for n in names}
            if not (names & {"Product", "Course", "Service"}):
                continue
            title = str(entity.get("name") or "").strip()
            offers = entity.get("offers") or {}
            offers = offers if isinstance(offers, list) else [offers]
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                name = str(offer.get("name") or title or "").strip()
                if not name:
                    continue
                avail = _schema_token(offer.get("availability"))
                until = str(offer.get("priceValidUntil") or "")[:10]
                if not avail and not until:
                    continue
                key = name.lower()
                if key not in out:
                    out[key] = {
                        "name": name[:150],
                        "availability": avail[:40],
                        "valid_until": until,
                        "url": offer.get("url") or entity.get("url") or url,
                    }
    return out


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _offer_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "addressCountry", "addressRegion", "text"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return _schema_token(value)


def commerce_policies(raw_html: list[tuple[str, str]]) -> list[dict]:
    """Printed return/shipping fields on Offer schema. Not a delivery model."""
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for url, html in raw_html or []:
        for entity in _jsonld(html or ""):
            if not isinstance(entity, dict):
                continue
            types = entity.get("@type")
            names = {types} if isinstance(types, str) else set(types or [])
            names = {str(n).split("/")[-1] for n in names}
            if not (names & {"Product", "Course", "Service"}):
                continue
            title = str(entity.get("name") or "").strip()
            offers = entity.get("offers") or {}
            offers = offers if isinstance(offers, list) else [offers]
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                name = str(offer.get("name") or title or "").strip()
                page = str(offer.get("url") or entity.get("url") or url)
                for policy in _as_list(offer.get("hasMerchantReturnPolicy")):
                    if not isinstance(policy, dict):
                        continue
                    parts: list[str] = []
                    days = policy.get("merchantReturnDays")
                    if days is not None and str(days).strip() != "":
                        parts.append(f"{str(days).strip()} merchantReturnDays")
                    cat = _schema_token(policy.get("returnPolicyCategory"))
                    if cat:
                        parts.append(cat)
                    country = _offer_text(policy.get("applicableCountry"))
                    if country:
                        parts.append(country)
                    if not parts:
                        continue
                    detail = "; ".join(parts)[:200]
                    key = ("return", name.lower(), detail.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({
                        "kind": "return",
                        "name": name[:150],
                        "detail": detail,
                        "url": page,
                    })
                for ship in _as_list(offer.get("shippingDetails")):
                    if not isinstance(ship, dict):
                        continue
                    parts = []
                    dest = _offer_text(ship.get("shippingDestination"))
                    if dest:
                        parts.append(dest)
                    rate = ship.get("shippingRate")
                    if isinstance(rate, dict):
                        value = rate.get("value") or rate.get("name")
                        currency = rate.get("currency") or rate.get("priceCurrency") or ""
                        if value is not None and str(value).strip() != "":
                            parts.append(f"{str(value).strip()} {currency}".strip())
                    elif isinstance(rate, str) and rate.strip():
                        parts.append(rate.strip())
                    if not parts:
                        continue
                    detail = "; ".join(parts)[:200]
                    key = ("shipping", name.lower(), detail.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({
                        "kind": "shipping",
                        "name": name[:150],
                        "detail": detail,
                        "url": page,
                    })
                if len(out) >= 12:
                    return out
    return out


CATALOG_FIELDS = (
    ("sku", "sku"),
    ("gtin", "gtin"),
    ("gtin8", "gtin"),
    ("gtin12", "gtin"),
    ("gtin13", "gtin"),
    ("gtin14", "gtin"),
    ("isbn", "isbn"),
    ("mpn", "mpn"),
    ("productID", "product_id"),
)


def _id_value(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        text = str(int(value)) if float(value).is_integer() else str(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        return ""
    if not text or len(text) > 80:
        return ""
    if RUPEE.search(text) or "₹" in text:
        return ""
    return text[:80]


def catalog_ids(raw_html: list[tuple[str, str]]) -> list[dict]:
    """sku / gtin / mpn / brand from Product schema. Never from visible ₹."""
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for url, html in raw_html or []:
        for entity in _jsonld(html or ""):
            if not isinstance(entity, dict):
                continue
            types = entity.get("@type")
            names = {types} if isinstance(types, str) else set(types or [])
            names = {str(n).split("/")[-1] for n in names}
            if not (names & {"Product", "Course", "Service"}):
                continue
            title = str(entity.get("name") or "").strip()[:150]
            page = str(entity.get("url") or url)
            brand = _id_value(_offer_text(entity.get("brand")))
            if brand:
                key = ("brand", brand.lower(), title.lower())
                if key not in seen:
                    seen.add(key)
                    out.append({"kind": "brand", "name": title, "value": brand,
                                "url": page})
            offers = entity.get("offers") or {}
            offers = offers if isinstance(offers, list) else [offers]
            pools = [entity, *[o for o in offers if isinstance(o, dict)]]
            for node in pools:
                for field, kind in CATALOG_FIELDS:
                    value = _id_value(node.get(field))
                    if not value:
                        continue
                    key = (kind, value.lower(), title.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({
                        "kind": kind,
                        "name": title,
                        "value": value,
                        "url": str(node.get("url") or page),
                    })
                    if len(out) >= 20:
                        return out
    return out


def analyse_products(products: list[dict], pages: list[Any],
                     tagline: str = "", raw_html: list[tuple[str, str]] | None = None
                     ) -> ProductIntel:
    """Build a battlecard from structured offers. Pure function."""
    offers: list[OfferRow] = []
    seen: set[tuple] = set()
    terms = offer_terms(raw_html or [])
    for raw in products:
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        key = (name.lower(), raw.get("price_inr"), raw.get("url"))
        if key in seen:
            continue
        seen.add(key)
        extra = terms.get(name.lower()) or {}
        offers.append(OfferRow(
            name=name[:150],
            kind=str(raw.get("kind") or "product"),
            price_inr=raw.get("price_inr"),
            rating=raw.get("rating"),
            rating_count=raw.get("rating_count"),
            url=raw.get("url"),
            availability=str(raw.get("availability") or extra.get("availability") or ""),
            valid_until=str(raw.get("valid_until") or extra.get("valid_until") or ""),
        ))
    offers.sort(key=lambda o: (o.price_inr is None, o.price_inr or 0, o.name.lower()))

    priced = [o.price_inr for o in offers if o.price_inr is not None]
    page_paths = " ".join(p.url.lower() for p in pages)
    has_pricing_page = bool(any("/pricing" in p.url.lower() or "/plans" in p.url.lower()
                                for p in pages))
    cta_blob = " ".join(" ".join(p.cta_hits) for p in pages)
    free_signal = any(w in cta_blob for w in ("free trial", "start free", "try for free"))

    visible = visible_rupee_prices(raw_html or [])
    policies = commerce_policies(raw_html or [])
    catalog = catalog_ids(raw_html or [])
    if not offers and not has_pricing_page and not visible and not catalog:
        return ProductIntel(
            assessed=False,
            reason_not_assessed=(
                "No Product/Course/Service schema, no pricing/plans page, and no "
                "visible ₹ amounts next to commercial words in the sampled crawl."),
            pricing_model="unpublished",
        )

    if priced and free_signal:
        model = "mixed"
    elif priced:
        model = "paid"
    elif free_signal or has_pricing_page:
        model = "free" if free_signal else "unpublished"
    else:
        model = "unpublished"

    kinds = sorted({o.kind for o in offers})
    positioning_bits = []
    if tagline:
        positioning_bits.append(tagline.strip()[:220])
    if kinds:
        positioning_bits.append("Published offer types: " + ", ".join(kinds) + ".")
    if priced:
        positioning_bits.append(
            f"Public INR ladder spans ₹{min(priced):,.0f}–₹{max(priced):,.0f} "
            f"across {len(priced)} priced offer(s).")

    gaps: list[str] = []
    if not priced and offers:
        gaps.append("Structured offers exist but none publish an INR price.")
    if not offers and has_pricing_page:
        gaps.append("A pricing/plans page was crawled but no Product schema was found.")
    if offers and not any(o.rating for o in offers):
        gaps.append("No aggregateRating is published on structured offers.")
    if "/pricing" not in page_paths and "/plans" not in page_paths:
        gaps.append("No dedicated pricing/plans URL was in the sample.")
    if visible and not priced:
        gaps.append("Visible ₹ amounts sit near commercial words but no INR Product schema.")
    if catalog and not priced:
        gaps.append("Catalog identifiers were printed; no INR price was on those offers.")

    return ProductIntel(
        assessed=True,
        pricing_model=model,
        offer_count=len(offers),
        price_floor=min(priced) if priced else None,
        price_ceiling=max(priced) if priced else None,
        ladder=offers[:20],
        positioning=" ".join(positioning_bits) or (
            "Catalog identifiers were printed." if catalog
            else "Offers were observed; no tagline."),
        gaps=gaps,
        visible_prices=visible,
        policies=policies,
        catalog=catalog,
    )
