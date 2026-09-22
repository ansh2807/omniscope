"""Proactive watch sweep (spec §31).

A watched website is re-fetched at the homepage only. This is not a full Deep
Analyze: it compares title, tech fingerprints and outbound social hosts to the
last sweep. Creators are skipped — profile collection is too expensive for a
background tick and would look like a silent re-bill.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from urllib.parse import urlparse

from sqlmodel import Session, select

from app.engine.discovery.expander import classify as classify_link
from app.engine.http import fetch
from app.models import Alert, Entity
from app.omni.events import ALERT_TRIGGERED, emit
from app.omni.feeds import discover_feed_urls, parse_feed
from app.omni.cards import analyse_cards
from app.omni.claims import analyse_claims
from app.omni.identity import analyse_identity
from app.omni.indexability import tokens_from_page
from app.omni.onpage import analyse_onpage
from app.omni.links import analyse_links
from app.omni.reviews import analyse_reviews
from app.omni.schema_intel import analyse_schema
from app.omni.site import SECURITY_HEADERS, from_headers
from app.omni.vendors import analyse_vendors
from app.omni.webintel import detect_tech, extract_page


def diff_homepage(previous: dict, current: dict) -> list[dict[str, str]]:
    """Pure function: two homepage snapshots → alert drafts."""
    drafts: list[dict[str, str]] = []
    prev_title = (previous.get("title") or "").strip()
    curr_title = (current.get("title") or "").strip()
    if prev_title and curr_title and prev_title != curr_title:
        drafts.append({
            "kind": "content", "severity": "watch",
            "title": "Homepage title changed",
            "detail": f"{prev_title[:80]} → {curr_title[:80]}",
        })
    prev_tech = set(previous.get("tech") or [])
    curr_tech = set(current.get("tech") or [])
    added, removed = sorted(curr_tech - prev_tech), sorted(prev_tech - curr_tech)
    if added or removed:
        parts = []
        if added:
            parts.append("added " + ", ".join(added))
        if removed:
            parts.append("removed " + ", ".join(removed))
        drafts.append({
            "kind": "tech", "severity": "info",
            "title": "Homepage technology fingerprint changed",
            "detail": "; ".join(parts),
        })
    prev_soc = set(previous.get("socials") or [])
    curr_soc = set(current.get("socials") or [])
    s_add, s_rem = sorted(curr_soc - prev_soc), sorted(prev_soc - curr_soc)
    if s_add or s_rem:
        parts = []
        if s_add:
            parts.append("new " + ", ".join(s_add))
        if s_rem:
            parts.append("gone " + ", ".join(s_rem))
        drafts.append({
            "kind": "social", "severity": "info",
            "title": "Homepage social links changed",
            "detail": "; ".join(parts),
        })
    prev_h1 = (previous.get("h1") or "").strip()
    curr_h1 = (current.get("h1") or "").strip()
    if prev_h1 and curr_h1 and prev_h1 != curr_h1:
        drafts.append({
            "kind": "content", "severity": "watch",
            "title": "Homepage H1 changed",
            "detail": f"{prev_h1[:80]} → {curr_h1[:80]}",
        })
    prev_feed = (previous.get("feed_title") or "").strip()
    curr_feed = (current.get("feed_title") or "").strip()
    if prev_feed and curr_feed and prev_feed != curr_feed:
        drafts.append({
            "kind": "content", "severity": "info",
            "title": "Latest first-party feed item changed",
            "detail": f"{prev_feed[:80]} → {curr_feed[:80]}",
        })
    prev_pub = (previous.get("feed_published") or "").strip()
    curr_pub = (current.get("feed_published") or "").strip()
    if prev_pub and curr_pub and prev_pub != curr_pub:
        drafts.append({
            "kind": "content", "severity": "info",
            "title": "First-party feed date changed",
            "detail": f"{prev_pub} → {curr_pub}",
        })
    prev_on = set(previous.get("onpage") or [])
    curr_on = set(current.get("onpage") or [])
    o_add, o_rem = sorted(curr_on - prev_on), sorted(prev_on - curr_on)
    if o_add or o_rem:
        parts = []
        if o_add:
            parts.append("new " + ", ".join(o_add))
        if o_rem:
            parts.append("gone " + ", ".join(o_rem))
        drafts.append({
            "kind": "onpage", "severity": "info",
            "title": "Homepage on-page surfaces changed",
            "detail": "; ".join(parts),
        })
    prev_ids = set(previous.get("ids") or [])
    curr_ids = set(current.get("ids") or [])
    i_add, i_rem = sorted(curr_ids - prev_ids), sorted(prev_ids - curr_ids)
    if i_add or i_rem:
        parts = []
        if i_add:
            parts.append("new " + ", ".join(i_add))
        if i_rem:
            parts.append("gone " + ", ".join(i_rem))
        drafts.append({
            "kind": "identity", "severity": "watch",
            "title": "Homepage printed identifier changed",
            "detail": "; ".join(parts),
        })
    prev_lang = (previous.get("lang") or "").strip()
    curr_lang = (current.get("lang") or "").strip()
    if prev_lang and curr_lang and prev_lang != curr_lang:
        drafts.append({
            "kind": "locale", "severity": "info",
            "title": "Homepage html lang changed",
            "detail": f"{prev_lang} → {curr_lang}",
        })
    prev_og = (previous.get("og_locale") or "").strip()
    curr_og = (current.get("og_locale") or "").strip()
    if prev_og and curr_og and prev_og != curr_og:
        drafts.append({
            "kind": "locale", "severity": "info",
            "title": "Homepage og:locale changed",
            "detail": f"{prev_og} → {curr_og}",
        })
    prev_types = set(previous.get("schema_types") or [])
    curr_types = set(current.get("schema_types") or [])
    t_add, t_rem = sorted(curr_types - prev_types), sorted(prev_types - curr_types)
    if t_add or t_rem:
        parts = []
        if t_add:
            parts.append("new " + ", ".join(t_add))
        if t_rem:
            parts.append("gone " + ", ".join(t_rem))
        drafts.append({
            "kind": "schema", "severity": "info",
            "title": "Homepage JSON-LD types changed",
            "detail": "; ".join(parts),
        })
    prev_hdr = set(previous.get("headers") or [])
    curr_hdr = set(current.get("headers") or [])
    h_add, h_rem = sorted(curr_hdr - prev_hdr), sorted(prev_hdr - curr_hdr)
    if h_add or h_rem:
        parts = []
        if h_add:
            parts.append("new " + ", ".join(h_add))
        if h_rem:
            parts.append("gone " + ", ".join(h_rem))
        drafts.append({
            "kind": "headers", "severity": "info",
            "title": "Homepage security headers changed",
            "detail": "; ".join(parts),
        })
    prev_etag = (previous.get("etag") or "").strip()
    curr_etag = (current.get("etag") or "").strip()
    if prev_etag and curr_etag and prev_etag != curr_etag:
        drafts.append({
            "kind": "freshness", "severity": "info",
            "title": "Homepage ETag changed",
            "detail": f"{prev_etag[:60]} → {curr_etag[:60]}",
        })
    prev_lm = (previous.get("last_modified") or "").strip()
    curr_lm = (current.get("last_modified") or "").strip()
    if prev_lm and curr_lm and prev_lm != curr_lm:
        drafts.append({
            "kind": "freshness", "severity": "info",
            "title": "Homepage Last-Modified changed",
            "detail": f"{prev_lm[:60]} → {curr_lm[:60]}",
        })
    prev_bot = set(previous.get("robots") or [])
    curr_bot = set(current.get("robots") or [])
    r_add, r_rem = sorted(curr_bot - prev_bot), sorted(prev_bot - curr_bot)
    if r_add or r_rem:
        parts = []
        if r_add:
            parts.append("new " + ", ".join(r_add))
        if r_rem:
            parts.append("gone " + ", ".join(r_rem))
        drafts.append({
            "kind": "robots", "severity": "watch",
            "title": "Homepage robots directives changed",
            "detail": "; ".join(parts),
        })
    prev_v = set(previous.get("verifications") or [])
    curr_v = set(current.get("verifications") or [])
    v_add, v_rem = sorted(curr_v - prev_v), sorted(prev_v - curr_v)
    if v_add or v_rem:
        parts = []
        if v_add:
            parts.append("new " + ", ".join(v_add))
        if v_rem:
            parts.append("gone " + ", ".join(v_rem))
        drafts.append({
            "kind": "claims", "severity": "info",
            "title": "Homepage verification meta changed",
            "detail": "; ".join(parts),
        })
    prev_me = set(previous.get("rel_me") or [])
    curr_me = set(current.get("rel_me") or [])
    m_add, m_rem = sorted(curr_me - prev_me), sorted(prev_me - curr_me)
    if m_add or m_rem:
        parts = []
        if m_add:
            parts.append("new " + ", ".join(m_add))
        if m_rem:
            parts.append("gone " + ", ".join(m_rem))
        drafts.append({
            "kind": "claims", "severity": "info",
            "title": "Homepage rel=me links changed",
            "detail": "; ".join(parts),
        })
    prev_sa = set(previous.get("same_as") or [])
    curr_sa = set(current.get("same_as") or [])
    sa_add, sa_rem = sorted(curr_sa - prev_sa), sorted(prev_sa - curr_sa)
    if sa_add or sa_rem:
        parts = []
        if sa_add:
            parts.append("new " + ", ".join(sa_add[:8]))
        if sa_rem:
            parts.append("gone " + ", ".join(sa_rem[:8]))
        drafts.append({
            "kind": "claims", "severity": "info",
            "title": "Homepage sameAs changed",
            "detail": "; ".join(parts),
        })
    prev_rt = set(previous.get("ratings") or [])
    curr_rt = set(current.get("ratings") or [])
    rt_add, rt_rem = sorted(curr_rt - prev_rt), sorted(prev_rt - curr_rt)
    if rt_add or rt_rem:
        parts = []
        if rt_add:
            parts.append("new " + ", ".join(rt_add[:8]))
        if rt_rem:
            parts.append("gone " + ", ".join(rt_rem[:8]))
        drafts.append({
            "kind": "reviews", "severity": "info",
            "title": "Homepage aggregateRating changed",
            "detail": "; ".join(parts),
        })
    prev_hr = set(previous.get("hours") or [])
    curr_hr = set(current.get("hours") or [])
    hr_add, hr_rem = sorted(curr_hr - prev_hr), sorted(prev_hr - curr_hr)
    if hr_add or hr_rem:
        parts = []
        if hr_add:
            parts.append("new " + ", ".join(hr_add[:8]))
        if hr_rem:
            parts.append("gone " + ", ".join(hr_rem[:8]))
        drafts.append({
            "kind": "schema", "severity": "info",
            "title": "Homepage opening hours changed",
            "detail": "; ".join(parts),
        })
    prev_ht = set(previous.get("howto_tools") or [])
    curr_ht = set(current.get("howto_tools") or [])
    ht_add, ht_rem = sorted(curr_ht - prev_ht), sorted(prev_ht - curr_ht)
    if ht_add or ht_rem:
        parts = []
        if ht_add:
            parts.append("new " + ", ".join(ht_add[:8]))
        if ht_rem:
            parts.append("gone " + ", ".join(ht_rem[:8]))
        drafts.append({
            "kind": "schema", "severity": "info",
            "title": "Homepage HowTo tools changed",
            "detail": "; ".join(parts),
        })
    prev_tw = (previous.get("twitter_site") or "").strip()
    curr_tw = (current.get("twitter_site") or "").strip()
    if prev_tw and curr_tw and prev_tw != curr_tw:
        drafts.append({
            "kind": "cards", "severity": "info",
            "title": "Homepage twitter:site changed",
            "detail": f"{prev_tw[:40]} → {curr_tw[:40]}",
        })
    prev_og = (previous.get("og_type") or "").strip()
    curr_og = (current.get("og_type") or "").strip()
    if prev_og and curr_og and prev_og != curr_og:
        drafts.append({
            "kind": "cards", "severity": "info",
            "title": "Homepage og:type changed",
            "detail": f"{prev_og} → {curr_og}",
        })
    prev_vend = set(previous.get("vendors") or [])
    curr_vend = set(current.get("vendors") or [])
    ve_add, ve_rem = sorted(curr_vend - prev_vend), sorted(prev_vend - curr_vend)
    if ve_add or ve_rem:
        parts = []
        if ve_add:
            parts.append("new " + ", ".join(ve_add[:8]))
        if ve_rem:
            parts.append("gone " + ", ".join(ve_rem[:8]))
        drafts.append({
            "kind": "vendors", "severity": "info",
            "title": "Homepage third-party hosts changed",
            "detail": "; ".join(parts),
        })
    prev_can = (previous.get("canonical") or "").strip()
    curr_can = (current.get("canonical") or "").strip()
    if prev_can and curr_can and prev_can != curr_can:
        drafts.append({
            "kind": "links", "severity": "info",
            "title": "Homepage canonical changed",
            "detail": f"{prev_can[:80]} → {curr_can[:80]}",
        })
    prev_links = set(previous.get("doc_links") or [])
    curr_links = set(current.get("doc_links") or [])
    li_add, li_rem = sorted(curr_links - prev_links), sorted(prev_links - curr_links)
    if li_add or li_rem:
        parts = []
        if li_add:
            parts.append("new " + ", ".join(li_add[:8]))
        if li_rem:
            parts.append("gone " + ", ".join(li_rem[:8]))
        drafts.append({
            "kind": "links", "severity": "info",
            "title": "Homepage document links changed",
            "detail": "; ".join(parts),
        })
    prev_csp = set(previous.get("csp_hosts") or [])
    curr_csp = set(current.get("csp_hosts") or [])
    c_add, c_rem = sorted(curr_csp - prev_csp), sorted(prev_csp - curr_csp)
    if c_add or c_rem:
        parts = []
        if c_add:
            parts.append("new " + ", ".join(c_add[:8]))
        if c_rem:
            parts.append("gone " + ", ".join(c_rem[:8]))
        drafts.append({
            "kind": "csp", "severity": "info",
            "title": "Homepage CSP hosts changed",
            "detail": "; ".join(parts),
        })
    prev_mod = (previous.get("article_modified") or "").strip()
    curr_mod = (current.get("article_modified") or "").strip()
    if prev_mod and curr_mod and prev_mod != curr_mod:
        drafts.append({
            "kind": "schema", "severity": "info",
            "title": "Homepage article dateModified changed",
            "detail": f"{prev_mod} → {curr_mod}",
        })
    prev_courses = set(previous.get("courses") or [])
    curr_courses = set(current.get("courses") or [])
    co_add, co_rem = sorted(curr_courses - prev_courses), sorted(prev_courses - curr_courses)
    if co_add or co_rem:
        parts = []
        if co_add:
            parts.append("new " + ", ".join(co_add[:8]))
        if co_rem:
            parts.append("gone " + ", ".join(co_rem[:8]))
        drafts.append({
            "kind": "schema", "severity": "info",
            "title": "Homepage course schema changed",
            "detail": "; ".join(parts),
        })
    prev_cp = set(previous.get("contact_points") or [])
    curr_cp = set(current.get("contact_points") or [])
    cp_add, cp_rem = sorted(curr_cp - prev_cp), sorted(prev_cp - curr_cp)
    if cp_add or cp_rem:
        parts = []
        if cp_add:
            parts.append("new " + ", ".join(cp_add[:8]))
        if cp_rem:
            parts.append("gone " + ", ".join(cp_rem[:8]))
        drafts.append({
            "kind": "schema", "severity": "info",
            "title": "Homepage ContactPoint changed",
            "detail": "; ".join(parts),
        })
    prev_il = set(previous.get("item_lists") or [])
    curr_il = set(current.get("item_lists") or [])
    il_add, il_rem = sorted(curr_il - prev_il), sorted(prev_il - curr_il)
    if il_add or il_rem:
        parts = []
        if il_add:
            parts.append("new " + ", ".join(il_add[:8]))
        if il_rem:
            parts.append("gone " + ", ".join(il_rem[:8]))
        drafts.append({
            "kind": "schema", "severity": "info",
            "title": "Homepage ItemList changed",
            "detail": "; ".join(parts),
        })
    prev_agg = set(previous.get("aggregate_offers") or [])
    curr_agg = set(current.get("aggregate_offers") or [])
    ag_add, ag_rem = sorted(curr_agg - prev_agg), sorted(prev_agg - curr_agg)
    if ag_add or ag_rem:
        parts = []
        if ag_add:
            parts.append("new " + ", ".join(ag_add[:8]))
        if ag_rem:
            parts.append("gone " + ", ".join(ag_rem[:8]))
        drafts.append({
            "kind": "schema", "severity": "info",
            "title": "Homepage AggregateOffer changed",
            "detail": "; ".join(parts),
        })
    prev_oc = set(previous.get("offer_catalogs") or [])
    curr_oc = set(current.get("offer_catalogs") or [])
    oc_add, oc_rem = sorted(curr_oc - prev_oc), sorted(prev_oc - curr_oc)
    if oc_add or oc_rem:
        parts = []
        if oc_add:
            parts.append("new " + ", ".join(oc_add[:8]))
        if oc_rem:
            parts.append("gone " + ", ".join(oc_rem[:8]))
        drafts.append({
            "kind": "schema", "severity": "info",
            "title": "Homepage OfferCatalog changed",
            "detail": "; ".join(parts),
        })
    prev_rev = (previous.get("last_reviewed") or "").strip()
    curr_rev = (current.get("last_reviewed") or "").strip()
    if prev_rev and curr_rev and prev_rev != curr_rev:
        drafts.append({
            "kind": "schema", "severity": "info",
            "title": "Homepage lastReviewed changed",
            "detail": f"{prev_rev} → {curr_rev}",
        })
    prev_sp = set(previous.get("speakable") or [])
    curr_sp = set(current.get("speakable") or [])
    sp_add, sp_rem = sorted(curr_sp - prev_sp), sorted(prev_sp - curr_sp)
    if sp_add or sp_rem:
        parts = []
        if sp_add:
            parts.append("new " + ", ".join(sp_add[:8]))
        if sp_rem:
            parts.append("gone " + ", ".join(sp_rem[:8]))
        drafts.append({
            "kind": "schema", "severity": "info",
            "title": "Homepage speakable changed",
            "detail": "; ".join(parts),
        })
    return drafts


def _header_names(headers: dict | None) -> list[str]:
    raw = {k.lower(): v for k, v in (headers or {}).items() if v}
    names = [name for name in SECURITY_HEADERS if name in raw]
    if raw.get("content-language"):
        names.append("content-language")
    return names


def snapshot_from_html(url: str, html: str, headers: dict | None = None) -> dict:
    facts = extract_page(url, html)
    tech = [t.name for t in detect_tech([(url, html)])]
    socials = []
    for link in facts.external_links:
        plat = classify_link(link)
        if plat and plat != "website" and plat not in socials:
            socials.append(plat)
    onpage = analyse_onpage([(url, html)])
    identity = analyse_identity([(url, html)])
    schema = analyse_schema([(url, html)])
    reviews = analyse_reviews([(url, html)])
    claims = analyse_claims([(url, html)])
    cards = analyse_cards([(url, html)])
    vendors = analyse_vendors([(url, html)])
    links = analyse_links([(url, html)], headers)
    header_intel = from_headers(headers, origin=urlparse(url).netloc)
    raw_headers = {k.lower(): v for k, v in (headers or {}).items() if v}
    return {
        "title": facts.title or facts.og.get("og:title") or "",
        "h1": (facts.h1[0] if facts.h1 else ""),
        "tech": tech,
        "socials": socials,
        "url": url,
        "feed_title": "",
        "feed_published": "",
        "onpage": sorted({
            f"{hit.kind}:{hit.provider}" for hit in onpage.hits
            if hit.kind and hit.provider}),
        "ids": sorted({
            f"{row.kind}:{row.value}" for row in identity.ids
            if row.kind in {"gstin", "cin", "lei"} and row.value}),
        "lang": (facts.lang or "").strip(),
        "og_locale": (facts.og.get("og:locale") or "").strip(),
        "schema_types": sorted(schema.types.keys()),
        "headers": _header_names(headers),
        "etag": raw_headers.get("etag", "")[:80],
        "last_modified": raw_headers.get("last-modified", "")[:80],
        "robots": tokens_from_page(html, headers),
        "verifications": list(claims.verifications),
        "rel_me": sorted({row.host for row in claims.rel_me if row.host}),
        "same_as": sorted({row.host for row in claims.same_as if row.host}),
        "twitter_site": cards.twitter_site,
        "og_type": cards.og_type,
        "vendors": list(vendors.unique),
        "canonical": links.canonical,
        "doc_links": sorted({f"{row.rel}:{row.host or row.url}" for row in links.rows}),
        "csp_hosts": list(header_intel.csp_hosts),
        "article_modified": max(
            (row.modified for row in schema.articles if row.modified),
            default=""),
        "courses": sorted({row.name for row in schema.courses if row.name}),
        "contact_points": sorted({
            row.contact_type or row.telephone or row.email
            for row in schema.contact_points
            if row.contact_type or row.telephone or row.email}),
        "item_lists": sorted({row.name for row in schema.item_lists if row.name}),
        "aggregate_offers": sorted({
            f"{row.name}:{row.low}-{row.high}" for row in schema.aggregate_offers
            if row.low or row.high or row.name}),
        "offer_catalogs": sorted({row.name for row in schema.offer_catalogs if row.name}),
        "last_reviewed": max(
            (row.last_reviewed for row in schema.web_pages if row.last_reviewed),
            default=""),
        "speakable": sorted({
            "|".join(row.selectors) or row.name
            for row in schema.speakable
            if row.selectors or row.name}),
        "ratings": sorted({
            f"{row.via}:{row.value}:{row.count}"
            for row in reviews.ratings
            if row.value or row.count}),
        "hours": sorted({
            f"{row.day}:{row.opens}-{row.closes}"
            for row in schema.hours
            if row.day or row.opens}),
        "howto_tools": sorted({
            name for row in schema.howtos for name in row.tools if name}),
    }


def _watch_state(entity: Entity) -> dict:
    raw = getattr(entity, "watch_json", None) or ""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def check_website(session: Session, entity: Entity) -> list[Alert]:
    url = entity.canonical_url or (f"https://{entity.domain}" if entity.domain else "")
    if not url:
        return []
    page = await fetch(url)
    if not page.ok or page.blocked_by_robots:
        return []
    current = snapshot_from_html(
        page.final_url or url, page.text, headers=page.headers)
    advertised = discover_feed_urls(page.final_url or url, page.text)
    if advertised:
        feed = await fetch(advertised[0])
        if feed.ok:
            items = parse_feed(feed.text, advertised[0])
            if items:
                current["feed_title"] = items[0].title
                current["feed_published"] = items[0].published
    previous = _watch_state(entity)
    drafts = diff_homepage(previous, current) if previous else []
    entity.watch_json = json.dumps(current)
    entity.updated_at = datetime.utcnow()
    session.add(entity)
    alerts: list[Alert] = []
    for draft in drafts:
        row = Alert(
            id=uuid.uuid4().hex[:12],
            org_id=entity.org_id,
            entity_id=entity.id,
            kind=draft["kind"],
            severity=draft["severity"],
            title=draft["title"],
            detail=draft["detail"],
        )
        session.add(row)
        alerts.append(row)
        emit(ALERT_TRIGGERED, entity_id=entity.id, kind=draft["kind"])
    return alerts


async def run_sweep(session: Session, org_id: str | None = None,
                    *, limit: int = 20, all_tenants: bool = False) -> dict:
    query = select(Entity).where(Entity.watched == True)  # noqa: E712
    if not all_tenants:
        if org_id is not None:
            query = query.where(Entity.org_id == org_id)
        else:
            query = query.where(Entity.org_id == None)  # noqa: E711
    rows = list(session.exec(query).all())[:limit]
    checked = 0
    skipped = 0
    alert_n = 0
    for entity in rows:
        if entity.kind != "website":
            skipped += 1
            continue
        found = await check_website(session, entity)
        checked += 1
        alert_n += len(found)
    session.commit()
    return {"checked": checked, "skipped_creators": skipped,
            "alerts": alert_n, "watched": len(rows)}
