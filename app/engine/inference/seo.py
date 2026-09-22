"""SEO and discoverability assessment.

Classifies a sampled branded results page, declared metadata and public autocomplete
associations. It does not infer search demand, traffic, ranking history or purchases.

Depends on the discovery layer having run. Without a search API key this module returns
an honest "not assessed" rather than a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.schemas import RawProfile, SearchHit

OWNED_HOSTS = ("instagram.com", "youtube.com", "youtu.be", "linkedin.com", "x.com",
               "twitter.com", "threads.net", "facebook.com", "t.me", "topmate.io",
               "superprofile.bio", "linktr.ee", "beacons.ai", "apps.apple.com",
               "play.google.com")
AGGREGATORS = ("socialblade", "hypeauditor", "favikon", "starngage", "ikaroa",
               "influencer", "tracxn", "crunchbase", "shiksha", "collegedunia")

INTENT = {
    "board_exams": "Informational / exam preparation",
    "commerce_subjects": "Informational / syllabus-driven",
    "entrance_cat": "Commercial investigation / exam preparation",
    "entrance_gov": "Commercial investigation / exam preparation",
    "cuet_admissions": "Navigational / deadline-sensitive",
    "finance_certifications": "Commercial investigation / career decision",
    "careers_jobs": "Informational to transactional",
    "study_abroad": "Commercial investigation / education decision",
    "entrepreneurship": "Informational",
    "investing": "Commercial investigation",
    "ai_tech": "Informational",
    "productivity": "Informational",
    "school_science": "Informational / exam preparation",
}


@dataclass
class SeoAssessment:
    assessed: bool = False
    reason_not_assessed: str = ""
    owns_page_one: str = "unknown"        # yes | partial | no | unknown
    ownership_share: float | None = None
    collision_risk: str = "unknown"       # low | medium | severe | unknown
    collision_note: str = ""
    competing_entities: list[str] = field(default_factory=list)
    owned_properties: list[str] = field(default_factory=list)
    third_party_citations: list[str] = field(default_factory=list)
    keyword_footprint: list[str] = field(default_factory=list)
    keyword_note: str = ""
    intent_clusters: list[dict] = field(default_factory=list)
    related_searches: list[str] = field(default_factory=list)
    autocomplete_intents: list[dict] = field(default_factory=list)
    autocomplete_note: str = ""
    grade: str = "—"
    verdict: str = ""


def _host(u: str) -> str:
    return urlparse(u).netloc.lower().replace("www.", "")


def assess(raw: RawProfile, sig) -> SeoAssessment:
    s = SeoAssessment()

    # ---- owned properties and third-party citations -------------------------
    for acc in raw.accounts:
        if acc.raw.get("analysis_eligible") is False:
            continue
        if acc.platform in ("website", "linktree", "superprofile", "topmate"):
            s.owned_properties.append(acc.url)
    for h in raw.search_hits:
        host = _host(h.url)
        if any(a in host for a in AGGREGATORS) and h.url not in s.third_party_citations:
            s.third_party_citations.append(h.url)
    s.third_party_citations = s.third_party_citations[:8]

    # ---- keyword footprint --------------------------------------------------
    kws: list[str] = []
    for acc in raw.accounts:
        if acc.raw.get("analysis_eligible") is False:
            continue
        kws.extend(acc.keywords)
    seen, uniq = set(), []
    for k in kws:
        kl = k.lower().strip()
        if kl and kl not in seen:
            seen.add(kl)
            uniq.append(k.strip())
    s.keyword_footprint = uniq[:40]
    if s.keyword_footprint:
        name_kw = [k for k in s.keyword_footprint
                   if raw.seed_handle and raw.seed_handle.lower()[:6] in k.lower()
                   or (raw.display_name or "").split(" ")[0].lower() in k.lower()]
        s.keyword_note = (
            f"{len(s.keyword_footprint)} declared channel keywords. "
            + (f"{len(name_kw)} of them are personal-brand terms. This is publisher-supplied "
               "metadata, not evidence of how many people search for the creator."
               if name_kw else
               "None are personal-brand terms; traffic sources and query demand are unknown."))

    # ---- intent clusters ----------------------------------------------------
    owned_hosts = {_host(a.url) for a in raw.accounts}
    for topic, score in sig.topic_rank[:6]:
        intent = INTENT.get(topic, "Informational")
        has_site = any(h not in OWNED_HOSTS for h in owned_hosts)
        s.intent_clusters.append({
            "cluster": topic.replace("_", " ").title(),
            "share": round(score * 100),
            "intent": intent,
            "value": "Search volume and ranking not measured",
            "gap": ("A custom-domain property exists, but keyword ranking was not checked."
                    if has_site else
                    "No custom-domain property was collected. Keyword demand and rankings "
                    "still require a keyword-specific search/volume provider."),
        })

    # ---- what people actually type (keyless autocomplete) -------------------
    kl = raw.keyless or {}
    s.related_searches = list(kl.get("related_searches") or [])[:30]
    s.autocomplete_intents = list(kl.get("autocomplete_intents") or [])
    if s.related_searches:
        s.autocomplete_note = (
            f"{len(s.related_searches)} live autocomplete suggestions for this name were read "
            f"from the public suggest endpoint. They indicate query associations, not search "
            f"volume, ranking position or the number of people who searched.")

    # ---- branded search health ---------------------------------------------
    name = (raw.display_name or raw.seed_handle or "").strip()
    name_hits = [h for h in raw.search_hits
                 if name and name.split(" ")[0].lower() in h.query.lower()]
    if not raw.search_hits:
        s.reason_not_assessed = (
            "No search provider was configured, so page-one ownership and name-collision "
            "risk could not be measured — those need a results page. "
            + (f"Search intent below was still measured keylessly from "
               f"{len(s.related_searches)} live autocomplete completions."
               if s.related_searches else
               "Add a search key to assess them."))
        s.grade = "partial" if s.related_searches else "not assessed"
        return s

    s.assessed = True
    top = name_hits[:10] or raw.search_hits[:10]
    owned_count = sum(1 for h in top if any(o in _host(h.url) for o in OWNED_HOSTS)
                      or _host(h.url) in owned_hosts)
    s.ownership_share = round(owned_count / max(len(top), 1), 2)
    s.owns_page_one = ("yes" if s.ownership_share >= 0.6 else
                       "partial" if s.ownership_share >= 0.3 else "no")

    # ---- name collision -----------------------------------------------------
    handle = (raw.seed_handle or "").lower()
    first = name.split(" ")[0].lower() if name else ""
    others: list[str] = []
    for h in top:
        blob = f"{h.title} {h.url}".lower()
        if handle and handle[:6] in blob:
            continue
        if first and first in blob and not any(o in _host(h.url) for o in owned_hosts):
            label = re.sub(r"\s*[-|–].*$", "", h.title)[:70]
            if label and label not in others:
                others.append(label)
    s.competing_entities = others[:6]
    n = len(s.competing_entities)
    s.collision_risk = "severe" if n >= 4 else "medium" if n >= 2 else "low"
    s.collision_note = (
        f"{n} distinct other entities rank for this name in the top results."
        if n else "No competing entities found ranking for this name.")

    # ---- grade --------------------------------------------------------------
    pts = 0
    pts += {"yes": 3, "partial": 2, "no": 0}.get(s.owns_page_one, 0)
    pts += {"low": 2, "medium": 1, "severe": 0}.get(s.collision_risk, 0)
    pts += 2 if any(_host(u) not in OWNED_HOSTS for u in s.owned_properties) else 0
    pts += 1 if s.third_party_citations else 0
    pts += 1 if s.keyword_footprint else 0
    s.grade = ["D", "D+", "C", "C+", "B", "B+", "A-", "A", "A"][min(pts, 8)]

    bits = []
    if s.owns_page_one == "no":
        bits.append("does not own page one for their own name")
    if s.collision_risk == "severe":
        bits.append("competes with several unrelated entities on the same name")
    if not any(_host(u) not in OWNED_HOSTS for u in s.owned_properties):
        bits.append("has no collected custom-domain property; the traffic or demand effect was "
                    "not measured")
    s.verdict = ("This creator " + "; ".join(bits) + "."
                 if bits else
                 "In the sampled branded results, creator-controlled/platform surfaces are "
                 "prominent and a custom-domain property was collected. Traffic and demand "
                 "remain unmeasured.")
    return s
