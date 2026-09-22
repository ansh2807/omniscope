"""Deterministic critic + synthesis (spec §27, without an LLM).

Agents in the spec receive structured evidence. This module is that pipeline:
it only restates measured gaps, conflicts, and already-computed opportunities.
It never adds a number that is not already on the payload.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ReasoningIntel(BaseModel):
    assessed: bool = True
    findings: list[str] = Field(default_factory=list)
    critiques: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    methodology: str = (
        "Findings are restated from scored dimensions, coverage slots and "
        "unavailable items already computed. No language model is called. "
        "A missing measurement stays missing.")


def synthesize_web(*, scores: list, opportunities: list[dict],
                   unavailable: list[dict], seo_map: dict | None,
                   review_intel: dict | None, competitor_intel: dict | None,
                   overall: float, feed_intel: dict | None = None,
                   schema_intel: dict | None = None,
                   surface_intel: dict | None = None,
                   legal_intel: dict | None = None,
                   identity_intel: dict | None = None,
                   onpage_intel: dict | None = None,
                   locale_intel: dict | None = None,
                   index_intel: dict | None = None,
                   product_intel: dict | None = None,
                   ads_intel: dict | None = None,
                   claims_intel: dict | None = None,
                   card_intel: dict | None = None,
                   vendor_intel: dict | None = None,
                   link_intel: dict | None = None,
                   header_intel: dict | None = None) -> ReasoningIntel:
    findings: list[str] = [
        f"Website intelligence score is {overall}/100 from six public dimensions."
    ]
    for score in scores:
        key = getattr(score, "key", None) or (score.get("key") if isinstance(score, dict) else "")
        val = getattr(score, "score", None)
        if val is None and isinstance(score, dict):
            val = score.get("score")
        label = getattr(score, "label", None) or (score.get("label") if isinstance(score, dict) else key)
        if val is not None and float(val) < 5:
            findings.append(f"{label} is weak at {val}/10 on the published formula.")
    sm = seo_map or {}
    missing = [s.get("slot") for s in sm.get("slots") or [] if s.get("status") == "missing"]
    if missing:
        findings.append("Coverage gaps: " + ", ".join(missing) + ".")
    ri = review_intel or {}
    if ri.get("ratings"):
        findings.append(
            f"{len(ri['ratings'])} AggregateRating node(s) printed — "
            "not a verified review volume.")
    elif ri.get("items"):
        findings.append(
            f"{len(ri['items'])} on-page Review body(ies) printed — "
            "not a sentiment score.")
    ci = competitor_intel or {}
    if ci.get("assessed") and ci.get("competitors"):
        findings.append(
            f"{len(ci['competitors'])} official-site rival(s) surfaced from search.")
    elif ci and not ci.get("assessed"):
        findings.append("Competitor list was not assessed: "
                        + (ci.get("reason") or "no provider."))
    fi = feed_intel or {}
    if fi.get("assessed") and fi.get("latest_published"):
        findings.append(
            f"Latest first-party feed item is dated {fi['latest_published']}.")
    elif fi and not fi.get("assessed"):
        findings.append("No first-party RSS/Atom feed was advertised.")
    si = schema_intel or {}
    if si.get("assessed") and si.get("types"):
        findings.append(
            "JSON-LD types observed: " + ", ".join(list(si["types"])[:8]) + ".")
    if si.get("faqs"):
        findings.append(f"{len(si['faqs'])} FAQ schema pair(s) printed on sampled pages.")
    if si.get("jobs"):
        findings.append(
            f"{len(si['jobs'])} JobPosting node(s) printed — not a hiring-volume score.")
    if si.get("nap") and (si["nap"].get("telephone") or si["nap"].get("address")
                          or si["nap"].get("hours")):
        findings.append("Organization schema published a telephone, address or hours.")
    if si.get("articles"):
        dated_n = sum(1 for a in si["articles"]
                      if isinstance(a, dict) and (a.get("published") or a.get("modified")))
        findings.append(
            f"{len(si['articles'])} Article/BlogPosting node(s); "
            f"{dated_n} printed a datePublished or dateModified field.")
    if si.get("courses"):
        findings.append(
            f"{len(si['courses'])} Course/program node(s) printed — not enrollment.")
    if si.get("contact_points"):
        findings.append(
            f"{len(si['contact_points'])} ContactPoint node(s) printed — not a helpdesk.")
    if si.get("item_lists"):
        findings.append(
            f"{len(si['item_lists'])} ItemList node(s) printed — not inventory.")
    if si.get("aggregate_offers"):
        findings.append(
            f"{len(si['aggregate_offers'])} AggregateOffer range(s) printed — "
            "not a market price.")
    if si.get("offer_catalogs"):
        findings.append(
            f"{len(si['offer_catalogs'])} OfferCatalog node(s) printed — "
            "not a complete catalog.")
    if si.get("speakable"):
        findings.append(
            f"{len(si['speakable'])} speakable selector set(s) printed — "
            "not a featured-snippet rank.")
    if si.get("web_pages"):
        reviewed_n = sum(
            1 for p in si["web_pages"]
            if isinstance(p, dict) and p.get("last_reviewed"))
        findings.append(
            f"{len(si['web_pages'])} WebPage card(s); "
            f"{reviewed_n} printed a lastReviewed field — not a verified edit.")
    if si.get("hours"):
        findings.append(
            f"{len(si['hours'])} opening-hours slot(s) printed — "
            "not an open-now verdict.")
    if si.get("howtos"):
        tool_n = sum(len(h.get("tools") or []) for h in si["howtos"]
                     if isinstance(h, dict))
        findings.append(
            f"{len(si['howtos'])} HowTo node(s) printed"
            + (f" with {tool_n} tool name(s)" if tool_n else "")
            + " — not a shopping list or completion forecast.")
    surf = surface_intel or {}
    links = [l for l in (surf.get("links") or []) if isinstance(l, dict) and l.get("kind")]
    if links:
        kinds = sorted({str(l["kind"]) for l in links})
        findings.append("Declared surfaces linked: " + ", ".join(kinds) + ".")
    if si.get("people"):
        findings.append(
            f"{len(si['people'])} Person node(s) printed — not a headcount.")
    if si.get("videos"):
        findings.append(f"{len(si['videos'])} VideoObject node(s) on sampled pages.")
    li = legal_intel or {}
    if li.get("assessed") and li.get("latest_updated"):
        findings.append(f"Latest sampled policy page is dated {li['latest_updated']}.")
    elif li and not li.get("assessed"):
        findings.append("No privacy/terms page was in the sampled crawl.")
    ii = identity_intel or {}
    if ii.get("ids"):
        kinds = sorted({str(r.get("kind")) for r in ii["ids"] if isinstance(r, dict) and r.get("kind")})
        findings.append("Printed identifiers: " + ", ".join(kinds) + ".")
    oi = onpage_intel or {}
    on_hits = [h for h in (oi.get("hits") or []) if isinstance(h, dict) and h.get("kind")]
    if on_hits:
        kinds = sorted({str(h["kind"]) for h in on_hits})
        findings.append("On-page surfaces: " + ", ".join(kinds) + ".")
    serving = si.get("serving") or {}
    if isinstance(serving, dict) and serving.get("area"):
        findings.append("Organization schema areaServed: " + str(serving["area"])[:80] + ".")
    if isinstance(serving, dict) and serving.get("employees"):
        findings.append(
            "numberOfEmployees printed as "
            + str(serving["employees"]) + " — not a verified headcount.")
    if si.get("apps"):
        findings.append(
            f"{len(si['apps'])} SoftwareApplication/MobileApplication node(s) "
            "— not an app-store scrape.")
    loc = locale_intel or {}
    langs = [x for x in (loc.get("langs") or []) if x]
    if langs:
        findings.append(
            "Printed html lang tag(s): " + ", ".join(langs[:6])
            + " — not a market or TAM.")
    ix = index_intel or {}
    if ix.get("noindex"):
        findings.append(
            f"{len(ix['noindex'])} sampled page(s) printed noindex — "
            "not a ranking forecast.")
    cat = [c for c in ((product_intel or {}).get("catalog") or [])
           if isinstance(c, dict) and c.get("kind")]
    if cat:
        kinds = sorted({str(c["kind"]) for c in cat})
        findings.append(
            "Printed catalog identifier kinds: " + ", ".join(kinds)
            + " — not a SKU invented from ₹.")
    ads = ads_intel or {}
    if ads.get("exchanges"):
        findings.append(
            "ads.txt exchanges declared: " + ", ".join(ads["exchanges"][:6])
            + " — not spend.")
    claims = claims_intel or {}
    if claims.get("verifications"):
        findings.append(
            "Verification meta present: " + ", ".join(claims["verifications"])
            + " — not a Search Console status.")
    if claims.get("rel_me"):
        findings.append(
            f"{len(claims['rel_me'])} rel=me link(s) printed — not a merge key.")
    if claims.get("same_as"):
        findings.append(
            f"{len(claims['same_as'])} sameAs URL(s) printed — not a merge key "
            "or follower count.")
    cards = card_intel or {}
    if cards.get("twitter_site"):
        findings.append(
            "twitter:site printed as " + str(cards["twitter_site"])[:40]
            + " — not a follower count.")
    vendors = vendor_intel or {}
    if vendors.get("unique"):
        findings.append(
            f"{len(vendors['unique'])} off-host script/resource host(s) — "
            "not a vendor contract.")
    links = link_intel or {}
    if links.get("canonical") or links.get("manifests") or links.get("rows"):
        findings.append(
            f"{len(links.get('rows') or [])} document link relation(s) printed "
            "— hrefs not fetched, not authorship.")
    header = header_intel or {}
    if header.get("csp_hosts"):
        findings.append(
            f"{len(header['csp_hosts'])} CSP host token(s) — not a live load "
            "list or vendor contract.")
    if si.get("jobs") and any(
            isinstance(j, dict) and j.get("salary") for j in si["jobs"]):
        findings.append(
            "JobPosting baseSalary was printed — not a compensation survey.")
    conflicts = (seo_map or {}).get("canonical_conflicts") or []
    if conflicts:
        findings.append(f"{len(conflicts)} canonical host mismatch(es) on sampled pages.")

    critiques = [
        "This synthesis does not inspect traffic, rankings, revenue or private CRM data.",
        "Search-led rivals are candidates, not a win/loss record.",
    ]
    for row in (unavailable or [])[:6]:
        item = row.get("item") if isinstance(row, dict) else ""
        if item:
            critiques.append(f"Unmeasured: {item}.")

    recs = [o.get("title") for o in (opportunities or []) if o.get("title")]
    if not recs:
        recs.append("No rule-driven opportunity fired on the sampled pages.")
    return ReasoningIntel(
        findings=findings[:18],
        critiques=critiques[:10],
        recommendations=recs[:8],
    )
