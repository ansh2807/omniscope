"""Side-by-side compare of two stored website investigations (spec §14, §30).

Only fields already on both payloads are compared. A missing measurement on
either side is INSUFFICIENT EVIDENCE, not a win. This is not TAM, share, or
a recommendation to buy.
"""
from __future__ import annotations

import json

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.models import Entity, Report
from app.omni.desk import WEB_NEED_GUIDE, build_web_desk


class CompareRow(BaseModel):
    field: str
    left: str
    right: str
    note: str = ""  # shared | left_only | right_only | both_missing | delta | observed


class CompareIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    left_name: str = ""
    right_name: str = ""
    left_domain: str = ""
    right_domain: str = ""
    left_href: str = ""
    right_href: str = ""
    left_score: float | None = None
    right_score: float | None = None
    score_delta: float | None = None
    verdict: str = ""
    rows: list[CompareRow] = Field(default_factory=list)
    shared_tech: list[str] = Field(default_factory=list)
    left_only_tech: list[str] = Field(default_factory=list)
    right_only_tech: list[str] = Field(default_factory=list)
    shared_socials: list[str] = Field(default_factory=list)
    shared_rivals: list[str] = Field(default_factory=list)
    left_job: str = ""
    right_job: str = ""
    desk_rows: list[CompareRow] = Field(default_factory=list)
    methodology: str = (
        "Both columns are last stored website reports. Deltas use the published "
        "score formula already on those reports. Empty cells were not measured "
        "for that subject — they are not zeros. Desk rows compare need status, "
        "not a winner.")


def _names(items: list, *keys: str) -> set[str]:
    out: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for key in keys:
            value = (item.get(key) or "").strip()
            if value:
                out.add(value)
                break
    return out


def _score_map(payload: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in payload.get("scores") or []:
        if not isinstance(row, dict):
            continue
        key = row.get("key") or row.get("label")
        val = row.get("score")
        if key is not None and val is not None:
            out[str(key)] = float(val)
    return out


def _seo_missing(payload: dict) -> set[str]:
    slots = ((payload.get("seo_map") or {}).get("slots") or [])
    return {s.get("slot") for s in slots if isinstance(s, dict) and s.get("status") == "missing" and s.get("slot")}


def _join(values: set[str]) -> str:
    return ", ".join(sorted(values)) if values else "—"


def _desk_of(payload: dict) -> dict:
    desk = payload.get("desk")
    if isinstance(desk, dict) and desk.get("needs"):
        return desk
    return build_web_desk(payload).model_dump()


def _need_map(desk: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for need in desk.get("needs") or []:
        if isinstance(need, dict) and need.get("id"):
            out[str(need["id"])] = need
    return out


def _need_cell(need: dict | None) -> str:
    if not need:
        return "unavailable"
    status = need.get("status") or "unavailable"
    evidence = (need.get("evidence") or "")[:90]
    return f"{status} — {evidence}" if evidence else status


def _need_note(left: dict | None, right: dict | None) -> str:
    left_ok = bool(left) and left.get("status") != "unavailable"
    right_ok = bool(right) and right.get("status") != "unavailable"
    if left_ok and right_ok:
        return "both_present"
    if left_ok:
        return "left_only"
    if right_ok:
        return "right_only"
    return "both_missing"


def compare_payloads(left: dict, right: dict, *,
                     left_href: str = "", right_href: str = "") -> CompareIntel:
    """Pure compare. Either payload empty → not assessed."""
    if not left or not right:
        return CompareIntel(
            assessed=False,
            reason="Need two stored website reports. Deep Analyze both subjects first.")
    left_domain = (left.get("domain") or "").lower()
    right_domain = (right.get("domain") or "").lower()
    if left_domain and left_domain == right_domain:
        return CompareIntel(
            assessed=False,
            left_name=left.get("entity_name") or "",
            right_name=right.get("entity_name") or "",
            left_domain=left_domain,
            right_domain=right_domain,
            reason="Both sides are the same domain. Pick two different investigations.")

    left_score = left.get("overall_score")
    right_score = right.get("overall_score")
    try:
        left_score_f = float(left_score) if left_score is not None else None
    except (TypeError, ValueError):
        left_score_f = None
    try:
        right_score_f = float(right_score) if right_score is not None else None
    except (TypeError, ValueError):
        right_score_f = None

    delta = None
    verdict = "Overall scores cannot be compared — one side has no stored score."
    if left_score_f is not None and right_score_f is not None:
        delta = round(right_score_f - left_score_f, 1)
        if abs(delta) < 1:
            verdict = ("Overall scores are within 1 point on the published website "
                       "formula. Treat as a tie. This is not traffic or share.")
        else:
            higher = right.get("entity_name") if delta > 0 else left.get("entity_name")
            verdict = (
                f"{higher} scores {abs(delta):.1f} points higher on the published "
                "website formula. That is not traffic, revenue, or market share.")

    left_tech = _names(left.get("tech") or [], "name")
    right_tech = _names(right.get("tech") or [], "name")
    left_socials = {
        (s.get("platform") or "").lower()
        for s in (left.get("socials") or [])
        if isinstance(s, dict) and s.get("platform") and not s.get("error")
    }
    right_socials = {
        (s.get("platform") or "").lower()
        for s in (right.get("socials") or [])
        if isinstance(s, dict) and s.get("platform") and not s.get("error")
    }
    left_rivals = _names((left.get("competitor_intel") or {}).get("competitors") or [],
                         "domain", "name")
    right_rivals = _names((right.get("competitor_intel") or {}).get("competitors") or [],
                          "domain", "name")

    rows: list[CompareRow] = [
        CompareRow(field="Score",
                   left="—" if left_score_f is None else str(left_score_f),
                   right="—" if right_score_f is None else str(right_score_f),
                   note="delta" if delta is not None else "both_missing"),
    ]
    scores_l = _score_map(left)
    scores_r = _score_map(right)
    for key in sorted(set(scores_l) | set(scores_r)):
        lv, rv = scores_l.get(key), scores_r.get(key)
        if lv is None or rv is None:
            note = "left_only" if rv is None and lv is not None else (
                "right_only" if lv is None else "both_missing")
        else:
            note = "delta"
        rows.append(CompareRow(
            field=key,
            left="—" if lv is None else str(lv),
            right="—" if rv is None else str(rv),
            note=note,
        ))

    miss_l, miss_r = _seo_missing(left), _seo_missing(right)
    if miss_l or miss_r or (left.get("seo_map") or right.get("seo_map")):
        rows.append(CompareRow(
            field="SEO gaps",
            left=_join(miss_l) if left.get("seo_map") else "not assessed",
            right=_join(miss_r) if right.get("seo_map") else "not assessed",
            note="observed" if (left.get("seo_map") and right.get("seo_map")) else "both_missing",
        ))

    risk_l = (left.get("risk_intel") or {}).get("level")
    risk_r = (right.get("risk_intel") or {}).get("level")
    if risk_l or risk_r:
        rows.append(CompareRow(
            field="Risk level",
            left=risk_l or "not assessed",
            right=risk_r or "not assessed",
            note="observed" if risk_l and risk_r else "both_missing",
        ))

    feed_l = (left.get("feed_intel") or {}).get("latest_published") or ""
    feed_r = (right.get("feed_intel") or {}).get("latest_published") or ""
    if feed_l or feed_r:
        rows.append(CompareRow(
            field="Latest feed date",
            left=feed_l or "not assessed",
            right=feed_r or "not assessed",
            note="observed" if feed_l and feed_r else "both_missing",
        ))
    types_l = set((left.get("schema_intel") or {}).get("types") or {})
    types_r = set((right.get("schema_intel") or {}).get("types") or {})
    if types_l or types_r:
        rows.append(CompareRow(
            field="JSON-LD types",
            left=", ".join(sorted(types_l)) or "not assessed",
            right=", ".join(sorted(types_r)) or "not assessed",
            note="observed" if types_l and types_r else "both_missing",
        ))
    faq_l = len((left.get("schema_intel") or {}).get("faqs") or [])
    faq_r = len((right.get("schema_intel") or {}).get("faqs") or [])
    if faq_l or faq_r:
        rows.append(CompareRow(
            field="FAQ schema rows",
            left=str(faq_l), right=str(faq_r), note="observed",
        ))
    job_l = {(j.get("title") or "") for j in
             ((left.get("schema_intel") or {}).get("jobs") or []) if isinstance(j, dict)}
    job_r = {(j.get("title") or "") for j in
             ((right.get("schema_intel") or {}).get("jobs") or []) if isinstance(j, dict)}
    job_l.discard("")
    job_r.discard("")
    if job_l or job_r:
        rows.append(CompareRow(
            field="JobPosting titles",
            left=", ".join(sorted(job_l)) or "—",
            right=", ".join(sorted(job_r)) or "—",
            note="observed",
        ))
    art_l = [a.get("published") for a in
             ((left.get("schema_intel") or {}).get("articles") or [])
             if isinstance(a, dict) and a.get("published")]
    art_r = [a.get("published") for a in
             ((right.get("schema_intel") or {}).get("articles") or [])
             if isinstance(a, dict) and a.get("published")]
    if art_l or art_r:
        rows.append(CompareRow(
            field="Latest article date",
            left=max(art_l) if art_l else "not assessed",
            right=max(art_r) if art_r else "not assessed",
            note="observed" if art_l and art_r else "both_missing",
        ))
    mod_l = [a.get("modified") for a in
             ((left.get("schema_intel") or {}).get("articles") or [])
             if isinstance(a, dict) and a.get("modified")]
    mod_r = [a.get("modified") for a in
             ((right.get("schema_intel") or {}).get("articles") or [])
             if isinstance(a, dict) and a.get("modified")]
    if mod_l or mod_r:
        rows.append(CompareRow(
            field="Latest article dateModified",
            left=max(mod_l) if mod_l else "not assessed",
            right=max(mod_r) if mod_r else "not assessed",
            note="observed" if mod_l and mod_r else "both_missing",
        ))
    course_l = {(c.get("name") or "") for c in
                ((left.get("schema_intel") or {}).get("courses") or [])
                if isinstance(c, dict) and c.get("name")}
    course_r = {(c.get("name") or "") for c in
                ((right.get("schema_intel") or {}).get("courses") or [])
                if isinstance(c, dict) and c.get("name")}
    if course_l or course_r:
        rows.append(CompareRow(
            field="Course / program names",
            left=", ".join(sorted(course_l)) or "—",
            right=", ".join(sorted(course_r)) or "—",
            note="observed",
        ))
    cp_l = {(c.get("contact_type") or c.get("telephone") or c.get("email") or "")
            for c in ((left.get("schema_intel") or {}).get("contact_points") or [])
            if isinstance(c, dict)}
    cp_r = {(c.get("contact_type") or c.get("telephone") or c.get("email") or "")
            for c in ((right.get("schema_intel") or {}).get("contact_points") or [])
            if isinstance(c, dict)}
    cp_l.discard("")
    cp_r.discard("")
    if cp_l or cp_r:
        rows.append(CompareRow(
            field="ContactPoint types",
            left=", ".join(sorted(cp_l)) or "—",
            right=", ".join(sorted(cp_r)) or "—",
            note="observed",
        ))
    il_l = {(c.get("name") or "") for c in
            ((left.get("schema_intel") or {}).get("item_lists") or [])
            if isinstance(c, dict) and c.get("name")}
    il_r = {(c.get("name") or "") for c in
            ((right.get("schema_intel") or {}).get("item_lists") or [])
            if isinstance(c, dict) and c.get("name")}
    if il_l or il_r:
        rows.append(CompareRow(
            field="ItemList names",
            left=", ".join(sorted(il_l)) or "—",
            right=", ".join(sorted(il_r)) or "—",
            note="observed",
        ))
    agg_l = {(c.get("name") or f"{c.get('low')}-{c.get('high')}")
             for c in ((left.get("schema_intel") or {}).get("aggregate_offers") or [])
             if isinstance(c, dict) and (c.get("low") or c.get("high") or c.get("name"))}
    agg_r = {(c.get("name") or f"{c.get('low')}-{c.get('high')}")
             for c in ((right.get("schema_intel") or {}).get("aggregate_offers") or [])
             if isinstance(c, dict) and (c.get("low") or c.get("high") or c.get("name"))}
    if agg_l or agg_r:
        rows.append(CompareRow(
            field="AggregateOffer names",
            left=", ".join(sorted(agg_l)) or "—",
            right=", ".join(sorted(agg_r)) or "—",
            note="observed",
        ))
    oc_l = {(c.get("name") or "") for c in
            ((left.get("schema_intel") or {}).get("offer_catalogs") or [])
            if isinstance(c, dict) and c.get("name")}
    oc_r = {(c.get("name") or "") for c in
            ((right.get("schema_intel") or {}).get("offer_catalogs") or [])
            if isinstance(c, dict) and c.get("name")}
    if oc_l or oc_r:
        rows.append(CompareRow(
            field="OfferCatalog names",
            left=", ".join(sorted(oc_l)) or "—",
            right=", ".join(sorted(oc_r)) or "—",
            note="observed",
        ))
    rev_l = [p.get("last_reviewed") for p in
             ((left.get("schema_intel") or {}).get("web_pages") or [])
             if isinstance(p, dict) and p.get("last_reviewed")]
    rev_r = [p.get("last_reviewed") for p in
             ((right.get("schema_intel") or {}).get("web_pages") or [])
             if isinstance(p, dict) and p.get("last_reviewed")]
    if rev_l or rev_r:
        rows.append(CompareRow(
            field="Latest lastReviewed",
            left=max(rev_l) if rev_l else "not assessed",
            right=max(rev_r) if rev_r else "not assessed",
            note="observed" if rev_l and rev_r else "both_missing",
        ))
    sp_l = {("|".join(s.get("selectors") or []) or s.get("name") or "")
            for s in ((left.get("schema_intel") or {}).get("speakable") or [])
            if isinstance(s, dict)}
    sp_r = {("|".join(s.get("selectors") or []) or s.get("name") or "")
            for s in ((right.get("schema_intel") or {}).get("speakable") or [])
            if isinstance(s, dict)}
    sp_l.discard("")
    sp_r.discard("")
    if sp_l or sp_r:
        rows.append(CompareRow(
            field="Speakable selectors",
            left=", ".join(sorted(sp_l)) or "—",
            right=", ".join(sorted(sp_r)) or "—",
            note="observed",
        ))
    hr_l = {(f"{c.get('day')}:{c.get('opens')}-{c.get('closes')}"
             if c.get("day") or c.get("opens") else "")
            for c in ((left.get("schema_intel") or {}).get("hours") or [])
            if isinstance(c, dict)}
    hr_r = {(f"{c.get('day')}:{c.get('opens')}-{c.get('closes')}"
             if c.get("day") or c.get("opens") else "")
            for c in ((right.get("schema_intel") or {}).get("hours") or [])
            if isinstance(c, dict)}
    hr_l.discard("")
    hr_r.discard("")
    if hr_l or hr_r:
        rows.append(CompareRow(
            field="Opening hours slots",
            left=", ".join(sorted(hr_l)) or "—",
            right=", ".join(sorted(hr_r)) or "—",
            note="observed",
        ))
    ht_l = set()
    for h in ((left.get("schema_intel") or {}).get("howtos") or []):
        if isinstance(h, dict):
            ht_l.update(h.get("tools") or [])
    ht_r = set()
    for h in ((right.get("schema_intel") or {}).get("howtos") or []):
        if isinstance(h, dict):
            ht_r.update(h.get("tools") or [])
    if ht_l or ht_r:
        rows.append(CompareRow(
            field="HowTo tools",
            left=", ".join(sorted(ht_l)) or "—",
            right=", ".join(sorted(ht_r)) or "—",
            note="observed",
        ))
    rat_l = [c.get("value") for c in
             ((left.get("review_intel") or {}).get("ratings") or [])
             if isinstance(c, dict) and c.get("value")]
    rat_r = [c.get("value") for c in
             ((right.get("review_intel") or {}).get("ratings") or [])
             if isinstance(c, dict) and c.get("value")]
    if not rat_l and (left.get("review_intel") or {}).get("aggregate_rating") is not None:
        rat_l = [str((left.get("review_intel") or {}).get("aggregate_rating"))]
    if not rat_r and (right.get("review_intel") or {}).get("aggregate_rating") is not None:
        rat_r = [str((right.get("review_intel") or {}).get("aggregate_rating"))]
    if rat_l or rat_r:
        rows.append(CompareRow(
            field="Printed aggregateRating",
            left=", ".join(rat_l) or "not assessed",
            right=", ".join(rat_r) or "not assessed",
            note="observed" if rat_l and rat_r else "both_missing",
        ))
    surf_l = {(s.get("kind") or "") for s in
              ((left.get("surface_intel") or {}).get("links") or [])
              if isinstance(s, dict) and s.get("kind")}
    surf_r = {(s.get("kind") or "") for s in
              ((right.get("surface_intel") or {}).get("links") or [])
              if isinstance(s, dict) and s.get("kind")}
    if surf_l or surf_r:
        rows.append(CompareRow(
            field="Declared surfaces",
            left=", ".join(sorted(surf_l)) or "—",
            right=", ".join(sorted(surf_r)) or "—",
            note="observed",
        ))
    legal_l = (left.get("legal_intel") or {}).get("latest_updated") or ""
    legal_r = (right.get("legal_intel") or {}).get("latest_updated") or ""
    if legal_l or legal_r:
        rows.append(CompareRow(
            field="Latest policy date",
            left=legal_l or "not assessed",
            right=legal_r or "not assessed",
            note="observed" if legal_l and legal_r else "both_missing",
        ))
    id_l = {(i.get("kind") or "") for i in
            ((left.get("identity_intel") or {}).get("ids") or [])
            if isinstance(i, dict) and i.get("kind")}
    id_r = {(i.get("kind") or "") for i in
            ((right.get("identity_intel") or {}).get("ids") or [])
            if isinstance(i, dict) and i.get("kind")}
    if id_l or id_r:
        rows.append(CompareRow(
            field="Printed identifier kinds",
            left=", ".join(sorted(id_l)) or "—",
            right=", ".join(sorted(id_r)) or "—",
            note="observed",
        ))
    on_l = {(h.get("provider") or h.get("kind") or "") for h in
            ((left.get("onpage_intel") or {}).get("hits") or [])
            if isinstance(h, dict) and (h.get("provider") or h.get("kind"))}
    on_r = {(h.get("provider") or h.get("kind") or "") for h in
            ((right.get("onpage_intel") or {}).get("hits") or [])
            if isinstance(h, dict) and (h.get("provider") or h.get("kind"))}
    if on_l or on_r:
        rows.append(CompareRow(
            field="On-page surfaces",
            left=", ".join(sorted(on_l)) or "—",
            right=", ".join(sorted(on_r)) or "—",
            note="observed",
        ))
    serve_l = ((left.get("schema_intel") or {}).get("serving") or {})
    serve_r = ((right.get("schema_intel") or {}).get("serving") or {})
    if not isinstance(serve_l, dict):
        serve_l = {}
    if not isinstance(serve_r, dict):
        serve_r = {}
    if serve_l.get("area") or serve_r.get("area"):
        rows.append(CompareRow(
            field="Area served",
            left=serve_l.get("area") or "not assessed",
            right=serve_r.get("area") or "not assessed",
            note="observed" if serve_l.get("area") and serve_r.get("area") else "both_missing",
        ))
    if serve_l.get("payments") or serve_r.get("payments"):
        rows.append(CompareRow(
            field="Payments accepted",
            left=serve_l.get("payments") or "not assessed",
            right=serve_r.get("payments") or "not assessed",
            note="observed",
        ))
    loc_l = {(x or "").strip() for x in
             ((left.get("locale_intel") or {}).get("langs") or []) if x}
    loc_r = {(x or "").strip() for x in
             ((right.get("locale_intel") or {}).get("langs") or []) if x}
    if loc_l or loc_r:
        rows.append(CompareRow(
            field="html lang tags",
            left=", ".join(sorted(loc_l)) or "not assessed",
            right=", ".join(sorted(loc_r)) or "not assessed",
            note="observed" if loc_l and loc_r else "both_missing",
        ))
    app_l = {(a.get("name") or "") for a in
             ((left.get("schema_intel") or {}).get("apps") or [])
             if isinstance(a, dict) and a.get("name")}
    app_r = {(a.get("name") or "") for a in
             ((right.get("schema_intel") or {}).get("apps") or [])
             if isinstance(a, dict) and a.get("name")}
    if app_l or app_r:
        rows.append(CompareRow(
            field="Application schema names",
            left=", ".join(sorted(app_l)) or "—",
            right=", ".join(sorted(app_r)) or "—",
            note="observed",
        ))
    ix_l = len((left.get("index_intel") or {}).get("noindex") or [])
    ix_r = len((right.get("index_intel") or {}).get("noindex") or [])
    if ix_l or ix_r:
        rows.append(CompareRow(
            field="noindex pages (sampled)",
            left=str(ix_l), right=str(ix_r), note="observed",
        ))
    cat_l = {(c.get("kind") or "") for c in
             ((left.get("product_intel") or {}).get("catalog") or [])
             if isinstance(c, dict) and c.get("kind")}
    cat_r = {(c.get("kind") or "") for c in
             ((right.get("product_intel") or {}).get("catalog") or [])
             if isinstance(c, dict) and c.get("kind")}
    if cat_l or cat_r:
        rows.append(CompareRow(
            field="Catalog identifier kinds",
            left=", ".join(sorted(cat_l)) or "—",
            right=", ".join(sorted(cat_r)) or "—",
            note="observed",
        ))
    lm_l = (left.get("header_intel") or {}).get("last_modified") or ""
    lm_r = (right.get("header_intel") or {}).get("last_modified") or ""
    if lm_l or lm_r:
        rows.append(CompareRow(
            field="Homepage Last-Modified",
            left=lm_l or "not assessed",
            right=lm_r or "not assessed",
            note="observed" if lm_l and lm_r else "both_missing",
        ))
    ads_l = set((left.get("ads_intel") or {}).get("exchanges") or [])
    ads_r = set((right.get("ads_intel") or {}).get("exchanges") or [])
    if ads_l or ads_r:
        rows.append(CompareRow(
            field="ads.txt exchanges",
            left=", ".join(sorted(ads_l)) or "—",
            right=", ".join(sorted(ads_r)) or "—",
            note="observed",
        ))
    ver_l = set((left.get("claims_intel") or {}).get("verifications") or [])
    ver_r = set((right.get("claims_intel") or {}).get("verifications") or [])
    if ver_l or ver_r:
        rows.append(CompareRow(
            field="Verification meta",
            left=", ".join(sorted(ver_l)) or "—",
            right=", ".join(sorted(ver_r)) or "—",
            note="observed",
        ))
    sa_l = {(row.get("host") or row.get("url") or "")
            for row in ((left.get("claims_intel") or {}).get("same_as") or [])
            if isinstance(row, dict)}
    sa_r = {(row.get("host") or row.get("url") or "")
            for row in ((right.get("claims_intel") or {}).get("same_as") or [])
            if isinstance(row, dict)}
    sa_l.discard("")
    sa_r.discard("")
    if sa_l or sa_r:
        rows.append(CompareRow(
            field="sameAs hosts",
            left=", ".join(sorted(sa_l)) or "—",
            right=", ".join(sorted(sa_r)) or "—",
            note="observed",
        ))
    tw_l = (left.get("card_intel") or {}).get("twitter_site") or ""
    tw_r = (right.get("card_intel") or {}).get("twitter_site") or ""
    if tw_l or tw_r:
        rows.append(CompareRow(
            field="twitter:site",
            left=tw_l or "not assessed",
            right=tw_r or "not assessed",
            note="observed" if tw_l and tw_r else "both_missing",
        ))
    vend_l = set((left.get("vendor_intel") or {}).get("unique") or [])
    vend_r = set((right.get("vendor_intel") or {}).get("unique") or [])
    if vend_l or vend_r:
        rows.append(CompareRow(
            field="Off-host resource hosts",
            left=str(len(vend_l)), right=str(len(vend_r)), note="observed",
        ))
    can_l = (left.get("link_intel") or {}).get("canonical") or ""
    can_r = (right.get("link_intel") or {}).get("canonical") or ""
    if can_l or can_r:
        rows.append(CompareRow(
            field="Printed canonical",
            left=can_l or "not assessed",
            right=can_r or "not assessed",
            note="observed" if can_l and can_r else "both_missing",
        ))
    csp_l = set((left.get("header_intel") or {}).get("csp_hosts") or [])
    csp_r = set((right.get("header_intel") or {}).get("csp_hosts") or [])
    if csp_l or csp_r:
        rows.append(CompareRow(
            field="CSP host tokens",
            left=str(len(csp_l)), right=str(len(csp_r)), note="observed",
        ))

    left_desk = _desk_of(left)
    right_desk = _desk_of(right)
    left_needs = _need_map(left_desk)
    right_needs = _need_map(right_desk)
    desk_rows = []
    for nid, title, _plain in WEB_NEED_GUIDE:
        ln, rn = left_needs.get(nid), right_needs.get(nid)
        desk_rows.append(CompareRow(
            field=title,
            left=_need_cell(ln),
            right=_need_cell(rn),
            note=_need_note(ln, rn),
        ))

    return CompareIntel(
        assessed=True,
        left_name=left.get("entity_name") or left_domain,
        right_name=right.get("entity_name") or right_domain,
        left_domain=left_domain,
        right_domain=right_domain,
        left_href=left_href,
        right_href=right_href,
        left_score=left_score_f,
        right_score=right_score_f,
        score_delta=delta,
        verdict=verdict,
        rows=rows,
        left_job=left_desk.get("job") or "",
        right_job=right_desk.get("job") or "",
        desk_rows=desk_rows,
        shared_tech=sorted(left_tech & right_tech),
        left_only_tech=sorted(left_tech - right_tech),
        right_only_tech=sorted(right_tech - left_tech),
        shared_socials=sorted(left_socials & right_socials),
        shared_rivals=sorted(left_rivals & right_rivals),
    )


def _payload_of(report: Report | None) -> dict:
    if not report or report.kind != "web" or not report.payload_json:
        return {}
    try:
        data = json.loads(report.payload_json)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def load_web_subject(session: Session, token: str, org_id: str | None) -> tuple[Report | None, dict]:
    """Resolve an entity id, report id, share slug, or domain to a web payload."""
    raw = (token or "").strip()
    if not raw:
        return None, {}

    def allowed(report: Report) -> bool:
        if org_id is not None:
            return report.org_id == org_id
        return report.org_id is None

    entity = session.get(Entity, raw)
    if entity and (org_id is None and entity.org_id is None or entity.org_id == org_id):
        report = session.get(Report, entity.last_report_id) if entity.last_report_id else None
        data = _payload_of(report)
        if data:
            return report, data

    report = session.get(Report, raw)
    if report and allowed(report):
        data = _payload_of(report)
        if data:
            return report, data

    slug = session.exec(select(Report).where(Report.share_slug == raw)).first()
    if slug and allowed(slug):
        data = _payload_of(slug)
        if data:
            return slug, data

    domain = raw.lower().removeprefix("https://").removeprefix("http://").split("/")[0]
    domain = domain.removeprefix("www.")
    query = select(Entity).where(Entity.domain == domain)
    if org_id is not None:
        query = query.where(Entity.org_id == org_id)
    else:
        query = query.where(Entity.org_id == None)  # noqa: E711
    hit = session.exec(query).first()
    if hit and hit.last_report_id:
        report = session.get(Report, hit.last_report_id)
        data = _payload_of(report)
        if data:
            return report, data
    return None, {}


def picker_subjects(session: Session, org_id: str | None) -> list[dict]:
    query = select(Entity).where(Entity.kind == "website").order_by(Entity.updated_at.desc())
    if org_id is not None:
        query = query.where(Entity.org_id == org_id)
    else:
        query = query.where(Entity.org_id == None)  # noqa: E711
    rows = []
    for entity in session.exec(query).all()[:80]:
        if not entity.last_report_id:
            continue
        rows.append({
            "id": entity.id,
            "name": entity.name,
            "domain": entity.domain,
            "score": entity.last_score,
        })
    return rows
