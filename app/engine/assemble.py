"""Assembles the full 13-section report payload from a RawProfile.

Everything that is *measured* lives in the analysis modules; everything that is
*modelled* lives in the inference engine. This module's only job is to run both, then
build the narrative sections that need both halves — overview, platform matrix,
opportunities and recommendations.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

from app.engine.inference import brand as brand_mod
from app.engine.inference import comments as comments_mod
from app.engine.inference import content as content_mod
from app.engine.inference import engine as infer
from app.engine.inference import funnel as funnel_mod
from app.engine.inference import growth as growth_mod
from app.engine.inference import diagnostics as diagnostics_mod
from app.engine.inference import platform as platform_mod
from app.engine.inference import seo as seo_mod
from app.engine.discovery.corroborate import audit as verification_audit
from app.engine.discovery.wikidata_identity import is_wikimedia_image
from app.engine.inference.agency_intelligence import analyse_agency_intelligence
from app.engine.inference.media_buy import build_media_buy_scorecard
from app.engine.inference.signals import Signals, extract
from app.omni.desk import build_creator_desk
from app.schemas import CreatorOverview, RawProfile, ReportPayload

ALL_PLATFORMS = ["instagram", "youtube", "linkedin", "x", "threads", "facebook",
                 "tiktok", "reddit", "bluesky", "mastodon", "github", "soundcloud", "pinterest", "hackernews", "telegram", "whatsapp", "website",
                 "topmate",
                 "superprofile", "linktree", "appstore", "playstore", "podcast"]

WALLED = {"linkedin": "authentication wall", "facebook": "partial authentication wall",
          "whatsapp": "no public metrics"}


def build(raw: RawProfile, report_id: str, *, competitors=None,
          comment_data=None) -> ReportPayload:
    verification = raw.verification or verification_audit(raw)
    raw.verification = verification
    sig = extract(raw)
    audience = infer.run(sig, raw)

    subs = sig.followers.get("youtube")
    content_accounts = [a for a in raw.accounts
                        if a.content and a.raw.get("analysis_eligible") is not False]
    exhaustive = bool(content_accounts) and all(
        a.raw.get("content_is_exhaustive") is True for a in content_accounts)
    ca = content_mod.analyse(raw.all_content(), subscribers=subs,
                             content_is_exhaustive=exhaustive)
    fa = funnel_mod.assess(raw)
    se = seo_mod.assess(raw, sig)

    comment_list, comment_notes = (comment_data or ([], []))
    cm = comments_mod.analyse(comment_list, notes=comment_notes,
                              creator_terms=sig.keywords + [sig.handle, sig.name])
    plats = platform_mod.analyse(raw, sig, ca)
    br = brand_mod.analyse(raw, sig, fa, se, ca, cm)
    gr = growth_mod.analyse(raw, sig, ca, fa, se, cm, br)
    dx = diagnostics_mod.analyse(raw, sig, audience, ca, fa, se, cm)
    agency = analyse_agency_intelligence(
        raw, signals=sig, audience=audience, content=ca,
        competitors=competitors, comments=cm, brand=br,
    ).to_dict()
    media_buy = build_media_buy_scorecard(
        agency=agency, signals=sig, content=ca, brand=br,
        diagnostics=dx, audience=audience,
    )

    _reconcile(audience, ca)
    sentiment = _sentiment(raw, ca, cm)
    overview = _overview(raw, sig)
    matrix = _platform_matrix(raw)
    opps = _opportunities(sig, ca, fa, se, audience, cm, gr)
    recs = _recommendations(sig, ca, fa, audience, cm, br)

    return ReportPayload(
        report_id=report_id,
        generated_at=datetime.utcnow(),
        subject_name=raw.display_name or raw.seed_handle or raw.seed_url,
        subject_handle=f"@{raw.seed_handle}" if raw.seed_handle else raw.seed_url,
        seed_url=raw.seed_url,
        headline_stats=_headline(sig, ca, fa, audience, agency, media_buy),
        raw=raw, audience=audience, overview=overview,
        content=ca, funnel=fa, seo=se, competitors=competitors,
        comments=cm, brand=br, growth=gr, agency=agency, media_buy=media_buy,
        diagnostics=dx, verification=verification, platforms=plats,
        platform_matrix=matrix, opportunities=opps, recommendations=recs,
        desk=build_creator_desk(
            name=raw.display_name or raw.seed_handle or raw.seed_url,
            handle=raw.seed_handle or "",
            overview=overview, audience=audience, signals=sig, content=ca,
            media_buy=media_buy, keyless=raw.keyless or {},
            accounts=raw.accounts,
        ).model_dump(),
        sentiment=sentiment,
        sources=[{"platform": a.platform, "url": a.url,
                  "role": a.raw.get("identity_role", "candidate"),
                  "status": a.raw.get("identity_status", "unreviewed")}
                 for a in raw.accounts],
        engine_version="3.7.0",
    )


# --------------------------------------------------------------- reconciliation
def _reconcile(audience, ca: content_mod.ContentAnalysis) -> None:
    """Measured seasonality beats the archetype prior. Say which one was used."""
    if ca.seasonality_measured and ca.seasonality:
        audience.seasonality = ca.seasonality
        audience.behaviours.insert(0, {
            "label": "Seasonality basis",
            "value": f"measured across {ca.active_months} active months",
            "note": (f"Peak {ca.peak_month}, trough {ca.trough_month}. Derived from actual "
                     "publish dates and view counts, not from a category assumption."),
        })
    if ca.cadence_per_month:
        audience.behaviours.append({
            "label": "Publishing cadence",
            "value": f"{ca.cadence_per_month} items/month",
            "note": "Measured across the observed publishing window.",
        })


# ------------------------------------------------------------------- overview
def _overview(raw: RawProfile, sig: Signals) -> CreatorOverview:
    ov = CreatorOverview(verified=sig.verified, press=sig.press_signals)
    accounts = [a for a in raw.accounts if a.raw.get("analysis_eligible") is not False]

    primary_bios = [(a.platform, a.bio) for a in accounts
                    if a.bio and a.raw.get("identity_role", "primary") == "primary"]
    bios = primary_bios or [(a.platform, a.bio) for a in accounts if a.bio]
    if bios:
        platform, bio = max(bios, key=lambda t: len(t[1]))
        ov.positioning = f'"{bio.strip()[:400]}" — as published on {platform}.'

    kl = raw.keyless or {}
    if not ov.positioning:
        extract = (kl.get("wikipedia_extract") or "").strip()
        title = kl.get("wikipedia_title") or "Wikipedia"
        if extract:
            ov.positioning = f'"{extract[:400]}" — Wikipedia ({title}).'
        elif (kl.get("wikidata_description") or "").strip():
            ov.positioning = (
                f'"{kl["wikidata_description"].strip()[:400]}" — Wikidata description.'
            )

    creds = []
    for pattern, label in [
        (r"\b(iim\s*[a-z]*)\b", "IIM"), (r"\b(iit\s*[a-z]*)\b", "IIT"),
        (r"\bmba\b", "MBA"), (r"\bfrm\b", "FRM"), (r"\bcfa\b", "CFA"),
        (r"\bca\b", "CA"), (r"\bacca\b", "ACCA"), (r"\bphd\b", "PhD"),
    ]:
        if re.search(pattern, sig.bio_text, re.I):
            creds.append(label)
    for school in kl.get("education") or []:
        label = f"{school} (Wikidata education)"
        if label not in creds:
            creds.append(label)
    for school in (kl.get("orcid_record") or {}).get("educations") or []:
        label = f"{school} (ORCID education)"
        if label not in creds:
            creds.append(label)
    for occ in kl.get("occupations") or []:
        label = f"{occ} (Wikidata)"
        if label not in creds:
            creds.append(label)
    ov.credentials = list(dict.fromkeys(creds))

    for a in accounts:
        ov.content_pillars.extend(a.highlights)
    for token in content_mod.recurring_title_tokens(
            [c.title for c in raw.all_content() if c.title]):
        label = f"{token} (from published titles)"
        if label not in ov.content_pillars:
            ov.content_pillars.append(label)
    for field in kl.get("fields_of_work") or []:
        label = f"{field} (Wikidata field of work)"
        if label not in ov.content_pillars:
            ov.content_pillars.append(label)
    for genre in kl.get("genres") or []:
        label = f"{genre} (Wikidata genre)"
        if label not in ov.content_pillars:
            ov.content_pillars.append(label)
    for cat in kl.get("wikipedia_categories") or []:
        label = f"{cat} (Wikipedia category)"
        if label not in ov.content_pillars:
            ov.content_pillars.append(label)
    ov.content_pillars = ov.content_pillars[:12]

    for a in accounts:
        for p in a.products:
            label = p.name if not p.price_inr else f"{p.name} (₹{int(p.price_inr):,})"
            if label not in ov.product_stack:
                ov.product_stack.append(label)
    ov.product_stack = ov.product_stack[:14]

    durations = [c.duration_seconds for c in raw.all_content() if c.duration_seconds]
    if durations:
        lo, hi = min(durations), max(durations)
        ov.format_range = (f"Published formats run from {lo // 60}m {lo % 60}s to "
                           f"{hi // 3600}h {(hi % 3600) // 60}m — "
                           + ("an unusually wide range, from micro-revision to marathon."
                              if hi > 3600 and lo < 120 else
                              "a consistent format discipline."))

    m = re.search(r"\b(?:based in|located in|from)\s+"
                  r"(noida|delhi|mumbai|pune|bengaluru|bangalore|hyderabad|chandigarh|"
                  r"kolkata|chennai|jaipur|lucknow)\b", sig.bio_text, re.I)
    if m:
        ov.base_location = m.group(1).title()
    if not ov.base_location and (kl.get("work_locations") or []):
        ov.base_location = f"{kl['work_locations'][0]} (Wikidata work location)"
    if not ov.base_location and (kl.get("residences") or []):
        ov.base_location = f"{kl['residences'][0]} (Wikidata residence)"
    if not ov.base_location and (kl.get("citizenships") or []):
        ov.base_location = f"{kl['citizenships'][0]} (Wikidata citizenship)"
    # P19 birthplace is not a current base. It is printed in press only.
    portrait = kl.get("image_url") or ""
    source = kl.get("image_source") or ""
    if is_wikimedia_image(portrait):
        ov.portrait_url = portrait
        ov.portrait_source = (source if source in ("wikipedia_summary", "wikidata_p18")
                              else "wikimedia")

    if kl.get("wikidata_description"):
        ov.press.append(f"Wikidata: {kl['wikidata_description']}")
    if kl.get("wikipedia_title"):
        ov.press.append(f"Wikipedia entry: {kl['wikipedia_title']}")
    if kl.get("pseudonyms"):
        ov.press.append(
            "Also known as: " + ", ".join(kl["pseudonyms"][:4])
            + " (Wikidata pseudonym)")
    for name in (kl.get("official_names") or [])[:2]:
        ov.press.append(f"Official name: {name} (Wikidata)")
    if kl.get("orcid"):
        ov.press.append(f"ORCID: {kl['orcid']} (Wikidata)")
    rec = kl.get("orcid_record") or {}
    if rec.get("biography") and not ov.positioning:
        ov.positioning = f'"{rec["biography"][:400]}" — ORCID biography.'
    for job in rec.get("employments") or []:
        ov.press.append(f"Employment: {job} (ORCID)")
    for work in rec.get("works") or []:
        ov.press.append(f"Work: {work} (ORCID)")
    pv = kl.get("pageviews") or {}
    if pv.get("views"):
        days = pv.get("days") or 0
        ov.press.append(
            f"Wikipedia pageviews: {int(pv['views']):,} in {days} days "
            "(Wikimedia pageview API, not site traffic or followers)")
    mb = kl.get("musicbrainz") or {}
    if mb.get("name"):
        kind = f" ({mb['type']})" if mb.get("type") else ""
        ov.press.append(f"MusicBrainz: {mb['name']}{kind}")
    if mb.get("country"):
        ov.press.append(
            f"MusicBrainz country listing: {mb['country']} "
            "(release territory, not a current base)")
    sp = kl.get("spotify_artist") or {}
    if sp.get("title"):
        ov.press.append(f"Spotify artist: {sp['title']} (oEmbed, not listeners)")
    for award in (kl.get("awards") or [])[:6]:
        ov.press.append(f"Award: {award} (Wikidata)")
    for work in (kl.get("notable_works") or [])[:6]:
        ov.press.append(f"Notable work: {work} (Wikidata)")
    for employer in (kl.get("employers") or [])[:4]:
        ov.press.append(f"Employer: {employer} (Wikidata)")
    for position in (kl.get("positions") or [])[:4]:
        ov.press.append(f"Position: {position} (Wikidata)")
    for place in (kl.get("birth_places") or [])[:2]:
        ov.press.append(f"Born: {place} (Wikidata)")
    if kl.get("languages"):
        ov.press.append(
            "Languages: " + ", ".join(kl["languages"][:6]) + " (Wikidata)")
    for nomination in (kl.get("nominations") or [])[:4]:
        ov.press.append(f"Nominated for: {nomination} (Wikidata)")
    for event in (kl.get("participations") or [])[:4]:
        ov.press.append(f"Participant: {event} (Wikidata)")
    for event in (kl.get("significant_events") or [])[:4]:
        ov.press.append(f"Significant event: {event} (Wikidata)")
    for org in (kl.get("memberships") or [])[:4]:
        ov.press.append(f"Member of: {org} (Wikidata)")
    for pod in (kl.get("podcasts") or [])[:6]:
        label = f"{pod['title']}" + (f" ({pod['publisher']})" if pod.get("publisher") else "")
        ov.press.append(f"Podcast: {label}")
    ov.press = list(dict.fromkeys(ov.press))[:24]
    return ov


# ------------------------------------------------------------ platform matrix
def _platform_matrix(raw: RawProfile) -> list[dict]:
    role_labels = {
        "primary": "Primary creator account",
        "associated_brand": "Associated brand/account",
        "secondary_channel": "Secondary/clips channel",
        "owned_property": "Creator-linked property",
        "indexed_profile": "Attributed profile (metrics unavailable)",
        "candidate": "Unverified candidate",
    }
    role_order = {"primary": 0, "associated_brand": 1, "secondary_channel": 2,
                  "owned_property": 3, "indexed_profile": 4, "candidate": 5}
    rows = []
    for p in ALL_PLATFORMS:
        found = sorted([a for a in raw.accounts if a.platform == p], key=lambda a: (
            role_order.get(a.raw.get("identity_role", "primary"), 9), -(a.followers or 0)))
        if found:
          for acc in found:
            verified = acc.raw.get("verified_via")
            identity_status = acc.raw.get("identity_status", "accepted")
            role = acc.raw.get("identity_role", "primary")
            tier = {
                "youtube_api_v3": "official API",
                "browser_render": "browser render (no key, logged out)",
                "public_channel_page": "plain HTTP parse",
                "public_profile_html": "plain HTTP parse",
                "public_profile_meta": "plain HTTP parse",
                "youtube_atom_feed": "YouTube public Atom feed",
                "wikidata": "Wikidata (third-party, dated)",
                "commercial_provider": "third-party provider",
            }.get(acc.raw.get("source", ""), acc.raw.get("source", "").replace("_", " "))
            if acc.raw.get("video_source") == "browser_render":
                tier += " + browser render for content"
            if acc.raw.get("video_source") == "youtube_atom_feed":
                tier += " + public Atom feed for recent uploads"
            if acc.raw.get("followers_precision") == "rounded":
                tier += " — rounded, low precision"
            if acc.raw.get("followers_source") == "wikidata":
                as_of = acc.raw.get("followers_as_of")
                tier += " — Wikidata follower count" + (f" as of {as_of}" if as_of else "")
            if verified and verified != "seed":
                tier += f" · verified by {verified.replace('_', ' ')}"
            rows.append({
                "platform": p,
                "status": "found" if acc.raw.get("analysis_eligible") is not False else "candidate",
                "role": role_labels.get(role, role.replace("_", " ").title()),
                "handle": acc.handle or "—",
                "url": acc.url,
                "followers": f"{acc.followers:,}" if acc.followers else "—",
                "items": len(acc.content),
                "tier": tier,
                "note": (("Candidate only; excluded from metrics. " if identity_status != "accepted"
                          else "") + ("; ".join(acc.errors)[:160] if acc.errors else tier)),
            })
        else:
            rejected = [r for r in (raw.rejected or []) if r["platform"] == p]
            seed_key = re.sub(r"[^a-z0-9]", "", (raw.seed_handle or "").lower())
            relevant = [r for r in rejected if seed_key and seed_key in
                        re.sub(r"[^a-z0-9]", "", r.get("url", "").lower())]
            if relevant:
                rows.append({
                    "platform": p, "status": "rejected", "handle": "—",
                    "role": "Rejected candidate",
                    "url": relevant[0]["url"], "followers": "—", "items": 0,
                    "tier": "candidate rejected",
                    "note": relevant[0]["reason"],
                })
            elif rejected:
                rows.append({
                    "platform": p, "status": "rejected", "handle": "—", "url": "",
                    "role": "Rejected candidate(s)",
                    "followers": "—", "items": 0, "tier": "candidates rejected",
                    "note": (f"{len(rejected)} candidate(s) were checked and excluded; "
                             "no attributable presence was verified."),
                })
            else:
                rows.append({
                    "platform": p, "status": "not found", "handle": "—", "url": "",
                    "role": "—",
                    "followers": "—", "items": 0, "tier": "—",
                    "note": WALLED.get(p, "no public presence discovered"),
                })
    return rows


def _review_source_label(raw: RawProfile) -> tuple[str | None, str]:
    """Name the surface the verbatim reviews actually came from."""
    labels: list[str] = []
    url = None
    for acc in raw.accounts:
        if acc.raw.get("analysis_eligible") is False or not acc.testimonials:
            continue
        url = acc.url
        if acc.platform == "podcast":
            labels.append("Apple Podcasts customer reviews")
        elif acc.platform in ("topmate", "superprofile"):
            labels.append("the creator's own booking page")
        else:
            labels.append(f"{acc.platform} public reviews")
    unique = list(dict.fromkeys(labels))
    if not unique:
        return None, ""
    if len(unique) == 1:
        return url, unique[0]
    if len(unique) == 2:
        return url, f"{unique[0]} and {unique[1]}"
    return url, ", ".join(unique[:-1]) + f", and {unique[-1]}"


# ---------------------------------------------------------------- sentiment
def _sentiment(raw: RawProfile, ca: content_mod.ContentAnalysis, cm=None) -> dict:
    texts: list[str] = []
    for acc in raw.accounts:
        if acc.raw.get("analysis_eligible") is False:
            continue
        if acc.testimonials:
            texts.extend(t.text for t in acc.testimonials)
    source, source_label = _review_source_label(raw)
    themes = content_mod.testimonial_themes(texts)
    if cm is not None and cm.available:
        extra = (
            f" A further {len(texts)} verbatim reviews were read from {source_label}."
            if texts and source_label else ""
        )
        scope = (
            f"{cm.sample_size:,} public YouTube comments were collected through the official "
            f"Data API across {cm.videos_sampled} videos, and are analysed in full below. "
            "Instagram comment threads remain login-walled and were NOT read — no Instagram "
            "comment is represented here, and YouTube comments are not substituted for them."
            + extra)
    else:
        review_bit = (
            f"What follows is built only on verbatim reviews from {source_label}, "
            f"plus title language across the {ca.measured_items} measured "
            "content items." if texts and source_label else
            "No verbatim public audience text was obtainable, so sentiment is reported as "
            "unavailable rather than modelled.")
        scope = (
            "Instagram comment threads require authentication and were not read. "
            + ("YouTube comment collection needs a YouTube Data API key, which was not "
               "configured for this run. " if cm is not None and not cm.available else "")
            + review_bit)

    out = {
        "verbatim_available": bool(texts),
        "sample_size": len(texts),
        "source": source,
        "source_label": source_label,
        "themes": themes,
        "scope_note": scope,
    }
    if themes:
        top = themes[0]
        out["read"] = (
            f"The dominant theme in {top['count']} of {len(texts)} public reviews is "
            f"\"{top['theme'].lower()}\". This describes the collected review texts only; "
            f"reviewer identity, purchases and representativeness are unknown. Treat the wording "
            f"as a creative hypothesis to test.")
    return out


# ------------------------------------------------------------- opportunities
def _opportunities(sig: Signals, ca, fa, se, audience, cm=None, gr=None) -> list[dict]:
    o: list[dict] = []

    if cm is not None and cm.available:
        intent = next((b for b in cm.buckets if b.label == "Buying intent"), None)
        if intent and intent.share >= 4:
            o.append({"area": "Monetisation", "effort": "Low", "impact": "Needs validation",
                      "what": (f"{intent.share}% of {cm.sample_size:,} collected public comments "
                               f"mention price, enrolment or links. Add a trackable response path "
                               f"and measure action; comment intent is not conversion.")})
        req = next((b for b in cm.buckets if b.label == "Content requests"), None)
        if req and req.share >= 4:
            ex = f' Example: "{req.examples[0]}"' if req.examples else ""
            o.append({"area": "Content", "effort": "Low", "impact": "Needs validation",
                      "what": (f"{req.share}% of the collected comment sample contains a direct "
                               f"content request. Test the request rather than generalising it "
                               f"to the whole audience.{ex}")})
        conf = next((b for b in cm.buckets if b.label == "Confusion"), None)
        if conf and conf.share >= 8:
            o.append({"area": "Product", "effort": "Medium", "impact": "Needs validation",
                      "what": (f"{conf.share}% of the classified comment sample expresses "
                               f"confusion. Test an explainer; this does not establish broader "
                               f"product demand.")})
        if cm.question_themes:
            q = cm.question_themes[0]
            o.append({"area": "Content", "effort": "Low", "impact": "Needs validation",
                      "what": (f'"{q.label}" is the largest classified question cluster at '
                               f'{q.share}% of the collected question sample. Test a dedicated '
                               f'asset and measure whether repeat questions decline.')})
    if gr is not None:
        for m in gr.missed[:2]:
            o.append({"area": "Growth", "effort": "Medium", "impact": "Needs validation",
                      "what": f"{m['missed']}. {m.get('evidence', '')}"})

    if len(sig.followers) > 1 and sig.platform_skew > 0.85:
        weak = sorted(((p, n) for p, n in sig.followers.items()
                       if p != sig.primary_platform), key=lambda t: t[1])
        if weak:
            p, n = weak[0]
            o.append({"area": "Platform", "effort": "High", "impact": "Needs validation",
                      "what": (f"Test the smaller {p} account before resourcing it. It holds "
                               f"{n:,} public follows against "
                               f"{sig.followers[sig.primary_platform]:,} on "
                               f"{sig.primary_platform}; current unique reach and audience fit "
                               "are unknown.")})

    if ca and ca.series_attrition and ca.series_attrition > 0.5:
        worst = ca.series[0] if ca.series else None
        detail = (f" \"{worst['name']}\" falls from {worst['first_views']:,} on part one to "
                  f"{worst['last_views']:,} on part {worst['parts']}." if worst else "")
        o.append({"area": "Content", "effort": "Low", "impact": "Needs validation",
                  "what": (f"Test a consolidated version of a multi-part series. Public "
                           f"view-count decline across numbered series averages "
                           f"{round(ca.series_attrition * 100)}%; this is not unique-viewer "
                           f"retention.{detail}")})

    if ca and ca.winning_patterns:
        w = ca.winning_patterns[0]
        o.append({"area": "Content", "effort": "Low", "impact": "High",
                  "what": (f"Test the \"{w.phrase}\" pattern again. Across {w.n} dated items "
                           f"it delivered a {w.lift}× median versus nearby-date items, with "
                           f"median {w.median_views:,} views. This is an association, not proof "
                           f"that the wording caused performance.")})

    if ca and ca.losing_patterns:
        l = ca.losing_patterns[0]
        o.append({"area": "Content", "effort": "Low", "impact": "Medium",
                  "what": (f"Retest or limit the \"{l.phrase}\" pattern. Across {l.n} dated "
                           f"items it delivered {l.lift}× the matched-date baseline, median "
                           f"{l.median_views:,} views. Topic and format may still explain it.")})

    if se and se.assessed and se.owns_page_one in ("no", "partial"):
        o.append({"area": "SEO", "effort": "Medium", "impact": "Very high",
                  "what": ("Investigate a rankable custom-domain property. "
                           + (se.intent_clusters[0]["cluster"] if se.intent_clusters
                              else "The core topic")
                           + " is present in the content model, while branded-result ownership "
                             "is weak. Search volume was not measured, so validate it first.")})

    if fa and not fa.owned_audience:
        o.append({"area": "Funnel", "effort": "Low", "impact": "High",
                  "what": ("Verify or build a first-party email/CRM list. Messaging channels "
                           "can provide permissioned reach, but no owned list count was observed.")})

    if fa and fa.spread and fa.spread < 3 and fa.rungs:
        o.append({"area": "Pricing", "effort": "Medium", "impact": "Needs validation",
                  "what": (f"Test whether buyers want another price tier. Public products span "
                           f"{fa.spread}× from ₹{int(fa.price_min):,} to "
                           f"₹{int(fa.price_max):,}; willingness to pay and conversion are "
                           "unavailable.")})

    if ca and ca.promo_gap and ca.promo_gap > 0.5:
        o.append({"area": "Monetisation", "effort": "Low", "impact": "Needs validation",
                  "what": (f"Test integrated versus standalone promotional content. The "
                           f"standalone-marker sample has median "
                           f"{ca.promo_median:,} views against {ca.organic_median:,} for "
                           f"other sampled titles — {round(ca.promo_gap * 100)}% lower. Topic, "
                           "age and distribution were not fully controlled.")})

    if audience.archetype in ("exam_prep_educator", "admissions_desk"):
        o.append({"area": "Product", "effort": "Medium", "impact": "Needs validation",
                  "what": ("Test interest in a post-exam/admission bridge offer. The content "
                           "cycle is observed; cohort churn, retention and buyer demand were "
                           "not measured.")})
    return o[:9]


# ---------------------------------------------------------- recommendations
def _recommendations(sig: Signals, ca, fa, audience, cm=None, br=None) -> list[dict]:
    recs: list[dict] = []
    subject = sig.name or (f"@{sig.handle}" if sig.handle else "this creator")
    interests = [x.get("topic", "") for x in audience.interests[:3] if x.get("topic")]
    stop = {"this", "that", "with", "from", "your", "what", "about", "how", "the",
            "and", "for", "you", "part", "video", "beginner", "tutorial", "minute"}
    observed = Counter(t for title in sig.titles for t in re.findall(r"[a-z0-9+]+", title.lower())
                       if len(t) > 3 and t not in stop)
    observed_focus = ", ".join(x for x, _ in observed.most_common(4))
    focus = ", ".join(interests[:2]) or observed_focus or "unclassified public content"
    top_domain = sig.topic_rank[0][0] if sig.topic_rank else ""

    if ca and ca.sub_to_view is not None and ca.sub_to_view < 0.02:
        recs.append({"priority": "Critical", "who": "Brand buying media",
                     "what": (f"Price {subject} from verified recent YouTube delivery, not the "
                              f"{sig.followers.get('youtube', 0):,}-subscriber headline."),
                     "why": (f"A median recent upload has {ca.current_median:,} public views "
                             f"against "
                             f"{sig.followers.get('youtube', 0):,} subscribers — "
                             f"{ca.sub_to_view * 100:.2f}%. Ask for a screen-recorded "
                              "Insights walkthrough before agreeing any rate. Public views are "
                              "not unique reach.")})

    if sig.primary_platform:
        share = round(sig.platform_skew * 100)
        recs.append({"priority": "High", "who": "Brand buying media",
                     "what": (f"Start {subject}'s diligence on {sig.primary_platform} "
                              f"({sig.followers[sig.primary_platform]:,} public follows), then "
                              "verify incremental cross-platform overlap."),
                     "why": (f"{share}% of summed public account follows are on "
                              f"{sig.primary_platform}. That is not unique audience share and "
                              f"does not establish the best campaign month.")})

    if audience.archetype == "generalist_creator" and top_domain == "creative_arts":
        recs.append({"priority": "Medium-high", "who": "Advising the creator",
                     "what": (f"For {subject}, compare one technique-led tutorial with one "
                              "process/portfolio story in the same publishing window."),
                     "why": (f"The boundary-matched corpus centres on {focus}, but public "
                             "content evidence does not establish which format drives saves, "
                             "commissions or purchases. Use matched-age views plus a tracked CTA.")})
    elif audience.archetype == "generalist_creator" and top_domain == "fitness_wellness":
        recs.append({"priority": "Critical", "who": "Brand buying media",
                     "what": (f"Separate {subject}'s workout, mobility and nutrition evidence; "
                              "verify qualifications and health claims before sponsorship."),
                     "why": (f"The observed corpus centres on {focus}. Content popularity does "
                             "not validate safety, credentials, outcomes or medical claims.")})
    elif audience.archetype == "generalist_creator" and top_domain in {
            "beauty_style", "food_cooking", "gaming", "travel", "entertainment"}:
        recs.append({"priority": "Medium-high", "who": "Brand buying media",
                     "what": (f"Design {subject}'s pilot around the observed {focus} content "
                              "cluster, with a matched-format control and one trackable action."),
                     "why": ("This is an observed content-domain classification only. It does "
                             "not establish audience demographics, purchase intent or brand lift.")})

    proof = (fa.social_proof.get("ratings") if fa else None) or 0
    if proof >= 25:
        offer = fa.rungs[0].name if fa and fa.rungs else "the observed offer path"
        recs.append({"priority": "High", "who": "Brand buying media",
                     "what": (f"Run a trackable pilot from {subject}'s content to "
                              f"{offer}; separate clicks, qualified leads and paid outcomes."),
                     "why": (f"{proof} public ratings provide social proof, while paid volume "
                              f"and conversion rate remain unavailable. Use a measured pilot "
                              f"before choosing CPA or flat-fee economics.")})

    if ca and ca.promo_gap and ca.promo_gap > 0.5:
        recs.append({"priority": "High", "who": "Brand buying media",
                     "what": (f"For {subject}, test integrated versus standalone placements "
                              f"against one KPI; sampled medians are {ca.organic_median:,} "
                              f"versus {ca.promo_median:,} views."),
                     "why": (f"Titles with promotional markers have "
                             f"{round(ca.promo_gap * 100)}% lower median public views in the "
                             "sample. Topic, age and distribution were not fully controlled.")})

    if sig.verified or len(sig.press_signals) >= 2:
        recs.append({"priority": "Medium-high", "who": "Brand buying media",
                     "what": (f"Verify {subject}'s identity and speaking evidence separately "
                              "from campaign-delivery evidence."),
                     "why": ("Carries "
                             + ("a verified account and " if sig.verified else "")
                             + (", ".join(sig.press_signals) or "public press coverage")
                              + " — useful diligence inputs that still need source verification.")})

    measured = ca.measured_items if ca else 0
    offer_scope = (f"{len(fa.rungs)} public offer(s) from ₹{int(fa.price_min):,} to "
                   f"₹{int(fa.price_max):,}" if fa and fa.rungs and fa.price_min is not None
                   and fa.price_max is not None else "no verified public price ladder")
    if audience.archetype == "generalist_creator":
        recs.append({"priority": "Critical", "who": "Building a product",
                     "what": (f"Do not assign a buyer persona to {subject} yet. First cluster "
                              f"responses to the observed {focus} content and interview the "
                              "people who take a trackable action."),
                     "why": (f"Across {measured} measured public items, the engine found "
                             "insufficient boundary-matched evidence for a supported audience "
                             f"taxonomy; {offer_scope}. Life stage and buyer identity are withheld.")})
    else:
        recs.append({"priority": "Medium", "who": "Building a product",
                     "what": (f"Validate whether {subject}'s {focus} audience has the same buyer, "
                              "problem and willingness to pay before extending the product stack."),
                     "why": (f"The hypothesis is derived from {measured} measured public content "
                             f"items and {offer_scope}; neither proves buyer identity or conversion. "
                             + (audience.activation[1]["do"] if len(audience.activation) > 1
                                else "Collect buyer interviews and transaction evidence."))})

    if cm is not None and cm.available:
        vocab = ", ".join(v['word'] for v in cm.vocabulary[:5]) or "the leading sampled terms"
        recs.append({"priority": "Medium-high", "who": "Brand buying media",
                     "what": (f"Test {subject} copy using the sampled vocabulary—{vocab}—"
                              "against a neutral control."),
                     "why": (f"Repeated sampled terms include: "
                             f"{', '.join(v['word'] for v in cm.vocabulary[:8])}. Sentiment is "
                             f"{cm.sentiment.get('positive', 0)}% positive within that sample; "
                             "it does not establish brand safety for all content.")})
    if br is not None and br.total < 30:
        weakest = min(br.pillars, key=lambda p: p.score)
        recs.append({"priority": "High", "who": "Brand buying media",
                     "what": (f"Resolve {subject}'s weakest brand-evidence pillar—"
                              f"{weakest.name} ({weakest.score}/10)—before setting deal terms."),
                     "why": (f"The evidence rubric scores {br.total}/50. "
                             f"{weakest.why}")})

    sequence: list[str] = []
    if ca and ca.winning_patterns:
        sequence.append(f'retest the observed "{ca.winning_patterns[0].phrase}" title pattern')
    elif ca and ca.top_performers:
        sequence.append(f'build one adjacent test to "{ca.top_performers[0].title[:70]}"')
    else:
        sequence.append(f"collect a dated performance sample for {focus}")
    if fa and not fa.owned_audience:
        sequence.append("instrument one permissioned email/CRM capture path")
    elif fa and fa.rungs:
        sequence.append(f"measure conversion into {fa.rungs[0].name}")
    else:
        sequence.append("publish one trackable response path before adding offers")
    if sig.primary_platform:
        sequence.append(f"request first-party {sig.primary_platform} reach and audience-overlap evidence")
    else:
        sequence.append("establish one measurable primary distribution surface")
    recs.append({"priority": "Medium", "who": "Advising the creator",
                 "what": (f"For {subject}, sequence: 1) {sequence[0]}; 2) {sequence[1]}; "
                          f"3) {sequence[2]}."),
                 "why": (f"This order responds to the observed {audience.archetype_label.lower()} "
                         "content system, funnel evidence and distribution concentration; it is "
                         "a test plan, not a forecast. "
                         + (audience.activation[2]["do"] if len(audience.activation) > 2
                            else "Measure each step before scaling."))})
    return recs


def headline_stats(sig, ca, fa, audience, agency=None, media_buy=None):
    return _headline(sig, ca, fa, audience, agency, media_buy)


def _headline(sig, ca, fa, audience, agency=None, media_buy=None) -> list[dict[str, str]]:
    stats: list[dict[str, str]] = []
    if sig.total_audience:
        stats.append({"label": "Summed public following", "value": f"{sig.total_audience:,}",
                      "note": " + ".join(f"{p} {n:,}" for p, n in
                                         sorted(sig.followers.items(), key=lambda kv: -kv[1]))
                              + " · cross-platform duplicates unknown"})
    if media_buy and media_buy.get("fit_score") is not None:
        stats.append({
            "label": "Media-buy fit",
            "value": f"{media_buy['fit_score']}",
            "note": f"{media_buy.get('label', '')} · coverage {media_buy.get('coverage_pct', 0)}%",
        })
    pct = audience.age.as_pct()
    if pct:
        observed = getattr(audience.age.status, "value", audience.age.status) == "observed"
        stats.append({
            "label": "Observed modal age" if observed else "Modelled life-stage",
            "value": max(pct, key=pct.get),
            "note": ((f"{max(pct.values())}% in supplied first-party age breakdown" if observed
                      else f"model allocation, not measured audience share · confidence "
                           f"{round(audience.age.confidence * 100)}%"))})
    if ca and ca.sub_to_view is not None and (sig.followers.get("youtube") or 0) >= 1_000:
        stats.append({"label": "Median views / subscribers",
                      "value": f"{ca.sub_to_view * 100:.2f}%",
                      "note": "current-sample ratio; not unique viewers or subscriber reach"})
    elif ca and ca.current_median:
        stats.append({"label": "Median recent views", "value": f"{ca.current_median:,}",
                      "note": f"across {ca.measured_items} measured items"})
    if fa and fa.social_proof.get("ratings"):
        stats.append({"label": "Public ratings",
                      "value": f"{fa.social_proof['ratings']}",
                      "note": "social proof; not treated as paid transaction count"})
    elif fa and fa.price_max:
        stats.append({"label": "Price ceiling", "value": f"₹{int(fa.price_max):,}",
                      "note": f"{len(fa.rungs)} observed SKUs"})
    if agency and isinstance(agency, dict):
        inf = agency.get("influence_score") or {}
        if inf.get("status") in ("calculated", "modelled") and isinstance(inf.get("value"), dict):
            score = inf["value"].get("score")
            if score is not None:
                stats.append({
                    "label": "Influence score",
                    "value": f"{score}",
                    "note": (f"{inf['value'].get('label', 'public-signal index')} · "
                             f"{inf.get('status', 'modelled').upper()} diligence proxy"),
                })
        reach = agency.get("estimated_reach") or {}
        if reach.get("status") == "modelled" and isinstance(reach.get("value"), dict):
            band = reach["value"].get("per_placement_range")
            if band:
                stats.append({
                    "label": "Est. placement views",
                    "value": f"{band[0]:,}–{band[1]:,}" if isinstance(band, (list, tuple)) and len(band) == 2
                             else str(band),
                    "note": "public-view proxy · not guaranteed impressions",
                })
    return stats[:6]
