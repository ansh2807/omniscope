"""Collection coverage of a stored website payload (spec §30, §41).

This is how much *we* measured, not how complete the company is. A slot is
``unavailable`` when the engine could not run, ``empty`` when it ran and found
nothing, and ``assessed`` when evidence exists. Never treat empty as zero share.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

SLOTS: tuple[tuple[str, str], ...] = (
    ("products", "product_intel"),
    ("competitors", "competitor_intel"),
    ("news", "news_intel"),
    ("feeds", "feed_intel"),
    ("reviews", "review_intel"),
    ("market", "market_intel"),
    ("awards", "award_intel"),
    ("seo", "seo_map"),
    ("risk", "risk_intel"),
    ("schema", "schema_intel"),
    ("robots", "robots_intel"),
    ("headers", "header_intel"),
    ("files", "public_intel"),
    ("surfaces", "surface_intel"),
    ("legal", "legal_intel"),
    ("identity", "identity_intel"),
    ("filings", "filings_intel"),
    ("onpage", "onpage_intel"),
    ("locale", "locale_intel"),
    ("index", "index_intel"),
    ("ads", "ads_intel"),
    ("claims", "claims_intel"),
    ("cards", "card_intel"),
    ("vendors", "vendor_intel"),
    ("links", "link_intel"),
)

ITEM_KEYS = {
    "product_intel": ("ladder", "offers", "visible_prices", "policies", "catalog"),
    "competitor_intel": ("competitors",),
    "news_intel": ("items",),
    "feed_intel": ("items",),
    "review_intel": ("items", "themes", "ratings"),
    "market_intel": ("participants",),
    "award_intel": ("mentions",),
    "seo_map": ("slots",),
    "risk_intel": ("items",),
    "schema_intel": ("items", "types"),
    "robots_intel": ("disallow", "sitemaps"),
    "header_intel": ("present", "csp_hosts"),
    "public_intel": ("hits",),
    "surface_intel": ("links",),
    "legal_intel": ("policies",),
    "identity_intel": ("ids",),
    "filings_intel": ("records", "identifiers"),
    "onpage_intel": ("hits",),
    "locale_intel": ("langs", "og_locales", "hreflang"),
    "index_intel": ("pages", "noindex"),
    "ads_intel": ("rows", "exchanges"),
    "claims_intel": ("verifications", "rel_me", "same_as"),
    "card_intel": ("og_type", "twitter_site", "banners"),
    "vendor_intel": ("hosts", "unique"),
    "link_intel": ("rows", "canonical", "manifests"),
}


class CoverageIntel(BaseModel):
    subject: str = ""
    domain: str = ""
    href: str = ""
    score: float | None = None
    slots: dict[str, str] = Field(default_factory=dict)
    assessed_n: int = 0
    empty_n: int = 0
    unavailable_n: int = 0
    socials: str = "empty"
    methodology: str = (
        "Slots describe this stored investigation, not the company's true "
        "completeness. unavailable = engine did not run. empty = ran, found nothing.")


def _intel_state(intel: dict | None, item_keys: tuple[str, ...]) -> str:
    if intel is None:
        return "missing"
    if not isinstance(intel, dict):
        return "missing"
    if intel.get("assessed") is False:
        return "unavailable"
    if "assessed" not in intel and not any(intel.get(k) for k in item_keys):
        return "missing"
    for key in item_keys:
        value = intel.get(key)
        if isinstance(value, list) and value:
            return "assessed"
        if isinstance(value, dict) and value:
            return "assessed"
        if isinstance(value, str) and value.strip():
            return "assessed"
    if intel.get("assessed") is True:
        return "empty"
    return "missing"


def _social_state(socials: list) -> str:
    if not socials:
        return "empty"
    live = [s for s in socials if isinstance(s, dict) and s.get("platform") and not s.get("error")]
    if live:
        return "assessed"
    if any(isinstance(s, dict) and s.get("error") for s in socials):
        return "empty"
    return "empty"


def from_payload(data: dict, *, subject: str = "", href: str = "") -> CoverageIntel:
    slots: dict[str, str] = {}
    for name, key in SLOTS:
        slots[name] = _intel_state(data.get(key), ITEM_KEYS.get(key, ()))
    socials = _social_state(data.get("socials") or [])
    slots["socials"] = socials
    schema = data.get("schema_intel") if isinstance(data.get("schema_intel"), dict) else None
    for name, key in (("faq", "faqs"), ("jobs", "jobs"), ("events", "events"),
                      ("nap", "nap"), ("articles", "articles"),
                      ("breadcrumbs", "breadcrumbs"), ("people", "people"),
                      ("videos", "videos"), ("howtos", "howtos"),
                      ("serving", "serving"), ("apps", "apps"),
                      ("courses", "courses"),
                      ("contact_points", "contact_points"),
                      ("item_lists", "item_lists"),
                      ("aggregate_offers", "aggregate_offers"),
                      ("offer_catalogs", "offer_catalogs"),
                      ("speakable", "speakable"),
                      ("web_pages", "web_pages"),
                      ("hours", "hours")):
        if schema is None:
            slots[name] = "missing"
        elif schema.get("assessed") is False:
            slots[name] = "unavailable"
        else:
            value = schema.get(key)
            if isinstance(value, list) and value:
                slots[name] = "assessed"
            elif isinstance(value, dict) and value:
                slots[name] = "assessed"
            elif schema.get("assessed") is True:
                slots[name] = "empty"
            else:
                slots[name] = "missing"
    assessed_n = sum(1 for v in slots.values() if v == "assessed")
    empty_n = sum(1 for v in slots.values() if v == "empty")
    unavailable_n = sum(1 for v in slots.values() if v in {"unavailable", "missing"})
    score = data.get("overall_score")
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
    return CoverageIntel(
        subject=subject or data.get("entity_name") or data.get("domain") or "",
        domain=data.get("domain") or "",
        href=href,
        score=score_f,
        slots=slots,
        assessed_n=assessed_n,
        empty_n=empty_n,
        unavailable_n=unavailable_n,
        socials=socials,
    )
