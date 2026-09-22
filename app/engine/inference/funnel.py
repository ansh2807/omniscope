"""Marketing funnel assessment.

Reads the creator's own commercial surfaces — price ladders, capture channels, free
assets, social proof — and scores how well the funnel is built. Every score carries the
observation that produced it, so a low mark is arguable rather than asserted.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import PlatformAccount, Product, RawProfile

CAPTURE_LABEL = {
    "telegram": "Telegram channel", "whatsapp": "WhatsApp channel",
    "linktree": "Link-in-bio page", "superprofile": "SuperProfile storefront",
    "topmate": "Topmate booking page", "appstore": "iOS app",
    "playstore": "Android app", "website": "Own website",
}
FREE_MARKERS = ("free", "download", "pdf", "notes", "sample paper", "mind map",
                "mindmap", "checklist", "template", "resource", "guide", "cheat sheet")


@dataclass
class Rung:
    tier: str          # lead_magnet | entry | core | premium
    name: str
    price_inr: float | None
    source: str


@dataclass
class Score:
    dimension: str
    value: int         # 0-10
    why: str


@dataclass
class FunnelAssessment:
    rungs: list[Rung] = field(default_factory=list)
    lead_magnets: list[str] = field(default_factory=list)
    capture_channels: list[str] = field(default_factory=list)
    routing_surfaces: list[str] = field(default_factory=list)
    permissioned_channels: list[str] = field(default_factory=list)
    owned_properties: list[str] = field(default_factory=list)
    owned_audience: bool = False       # true only with explicit list/CRM evidence
    owned_audience_note: str = ""
    social_proof: dict = field(default_factory=dict)
    price_min: float | None = None
    price_max: float | None = None
    spread: float | None = None
    scores: list[Score] = field(default_factory=list)
    total: int = 0
    stages: list[dict] = field(default_factory=list)
    strength: str = ""
    gap: str = ""


def _classify(products: list[Product]) -> list[Rung]:
    priced = [p for p in products if p.price_inr]
    if not priced:
        return []
    prices = sorted({p.price_inr for p in priced})
    lo, hi = prices[0], prices[-1]
    rungs: list[Rung] = []
    for p in sorted(priced, key=lambda x: x.price_inr):
        if len(prices) == 1:
            tier = "core"
        elif hi / max(lo, 1) < 1.8:
            tier = "core"
        elif p.price_inr <= lo * 1.35:
            tier = "entry"
        elif p.price_inr >= hi * 0.7:
            tier = "premium"
        else:
            tier = "core"
        rungs.append(Rung(tier=tier, name=p.name, price_inr=p.price_inr,
                          source=p.url or ""))
    return rungs


def assess(raw: RawProfile) -> FunnelAssessment:
    fa = FunnelAssessment()
    products: list[Product] = []
    free_assets: set[str] = set()

    for acc in raw.accounts:
        if acc.raw.get("analysis_eligible") is False:
            continue
        products.extend(acc.products)
        if acc.platform in CAPTURE_LABEL:
            label = CAPTURE_LABEL[acc.platform]
            if label not in fa.capture_channels:
                fa.capture_channels.append(label)
            if acc.platform in ("telegram", "whatsapp"):
                fa.permissioned_channels.append(label)
            elif acc.platform == "website":
                fa.owned_properties.append(label)
            else:
                fa.routing_surfaces.append(label)
        # A free video title is content, not a lead magnet. Count only an explicit free
        # product/resource surfaced in the bio, highlights or product catalogue.
        offer_blob = " ".join([acc.bio or "", " ".join(acc.highlights)]).lower()
        for marker in FREE_MARKERS:
            if marker in offer_blob:
                free_assets.add(marker)
        for product in acc.products:
            if product.price_inr == 0:
                free_assets.add(product.name)
        if acc.raw.get("email_list") or acc.raw.get("crm_contacts"):
            fa.owned_audience = True
        if acc.raw.get("rating_count"):
            fa.social_proof = {
                "ratings": int(acc.raw["rating_count"]),
                "score": acc.raw.get("rating"),
                "testimonials": len(acc.testimonials),
                "source": acc.url,
            }

    fa.lead_magnets = sorted(free_assets)[:8]
    fa.rungs = _classify(products)
    if fa.rungs:
        prices = [r.price_inr for r in fa.rungs if r.price_inr]
        fa.price_min, fa.price_max = min(prices), max(prices)
        fa.spread = round(fa.price_max / max(fa.price_min, 1), 1)

    fa.routing_surfaces = list(dict.fromkeys(fa.routing_surfaces))
    fa.permissioned_channels = list(dict.fromkeys(fa.permissioned_channels))
    fa.owned_properties = list(dict.fromkeys(fa.owned_properties))
    fa.owned_audience_note = (
        "Explicit first-party list/CRM evidence was supplied."
        if fa.owned_audience else
        "No email-list or CRM count was observed. Messaging channels are permissioned reach, "
        "while websites, link pages and storefronts are routes—not proof of an owned audience.")

    fa.scores = _score(fa, raw)
    fa.total = sum(s.value for s in fa.scores)
    fa.stages = _stages(fa, raw)
    fa.strength, fa.gap = _verdict(fa)
    return fa


def _score(fa: FunnelAssessment, raw: RawProfile) -> list[Score]:
    n_free = len(fa.lead_magnets)
    if n_free >= 4:
        lm = 9
        why_lm = f"{n_free} explicit free-resource or zero-price offer signals were observed."
    elif n_free >= 2:
        lm = 6
        why_lm = f"{n_free} free-asset signals found. Adequate, not exceptional."
    else:
        lm = 3
        why_lm = "Little evidence of a deliberate free asset designed to start a relationship."

    n_cap = len(fa.permissioned_channels)
    cap = min(10, 2 + n_cap * 3)
    why_cap = (f"Permissioned contact channels observed: {', '.join(fa.permissioned_channels)}."
               if fa.permissioned_channels else
               "No email, Telegram or WhatsApp capture channel was observed. Link pages and "
               "storefronts route traffic but do not retain contact permission.")
    if fa.routing_surfaces:
        why_cap += f" Routing surfaces: {', '.join(fa.routing_surfaces)}."

    if fa.spread and fa.spread >= 8:
        ladder, why_ladder = 9, (
            f"Prices run ₹{int(fa.price_min):,} to ₹{int(fa.price_max):,}, a {fa.spread}× "
            f"spread across {len(fa.rungs)} rungs. This is offer architecture only; buyer "
            "movement between rungs was not measured.")
    elif fa.spread and fa.spread >= 3:
        ladder, why_ladder = 6, (
            f"A {fa.spread}× spread across {len(fa.rungs)} rungs. A public ladder exists; "
            "affordability and trial behaviour are unavailable.")
    elif fa.rungs:
        ladder, why_ladder = 3, (
            f"{len(fa.rungs)} priced products clustered tightly. Effectively one price "
            "point, so there is no trial-to-commitment path.")
    else:
        ladder, why_ladder = 1, "No public pricing found on any owned surface."

    sp = fa.social_proof
    if sp.get("ratings", 0) >= 25:
        proof, why_proof = 8, (
            f"{sp['ratings']} public ratings at {sp.get('score', '—')}/5 with "
            f"{sp.get('testimonials', 0)} collected written review texts. This is strong "
            "social proof, but the rating count is not treated as paid transactions.")
    elif sp.get("ratings"):
        proof, why_proof = 6, f"{sp['ratings']} public ratings visible."
    else:
        proof, why_proof = 3, ("No public rating or review count found. Social proof is "
                               "assertion rather than evidence.")

    owned = 8 if fa.owned_audience else 1
    why_owned = (fa.owned_audience_note
                  if fa.owned_audience else
                 fa.owned_audience_note)

    conv = 1
    why_conv = ("Public products and ratings do not reveal completed purchases, conversion "
                "rate or revenue. No first-party conversion data was supplied.")

    repeat = 6 if any("app" in c.lower() for c in fa.capture_channels) else 4 if \
        fa.permissioned_channels else 2
    why_repeat = ("An app provides a repeat-access surface; retention itself is not public."
                   if repeat == 6 else
                   "A messaging channel allows repeat contact; retention rate is not public."
                   if repeat == 4 else "No repeat mechanism found.")

    return [
        Score("Lead magnet", lm, why_lm),
        Score("Capture mechanism", cap, why_cap),
        Score("Price laddering", ladder, why_ladder),
        Score("Social proof", proof, why_proof),
        Score("Owned audience", owned, why_owned),
        Score("Conversion evidence", conv, why_conv),
        Score("Retention / repeat", repeat, why_repeat),
    ]


def _stages(fa: FunnelAssessment, raw: RawProfile) -> list[dict]:
    reach = sum(a.followers or 0 for a in raw.accounts)
    entry = [r for r in fa.rungs if r.tier == "entry"]
    core = [r for r in fa.rungs if r.tier == "core"]
    prem = [r for r in fa.rungs if r.tier == "premium"]

    def fmt(rs: list[Rung]) -> str:
        if not rs:
            return "none found"
        cheapest = min(rs, key=lambda r: r.price_inr or 0)
        return f"{cheapest.name[:52]} — ₹{int(cheapest.price_inr):,}"

    return [
        {"stage": "Awareness", "width": 100,
         "detail": f"{reach:,} summed public account follows (not unique people)"},
        {"stage": "Interest", "width": 78,
         "detail": ", ".join(fa.lead_magnets[:5]) or "no distinct free asset identified"},
        {"stage": "Capture", "width": 56,
         "detail": ", ".join(fa.permissioned_channels) or "no permissioned capture observed"},
        {"stage": "Trial", "width": 36, "detail": fmt(entry)},
        {"stage": "Purchase offer", "width": 22, "detail": fmt(core)},
        {"stage": "Premium", "width": 13, "detail": fmt(prem)},
    ]


def _verdict(fa: FunnelAssessment) -> tuple[str, str]:
    best = max(fa.scores, key=lambda s: s.value)
    worst = min(fa.scores, key=lambda s: s.value)
    return (f"{best.dimension} ({best.value}/10). {best.why}",
            f"{worst.dimension} ({worst.value}/10). {worst.why}")
