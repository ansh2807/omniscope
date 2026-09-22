"""NEXUS — the central intelligence planner.

Given a classified input, NEXUS decides which engines run and why, then executes the
plan. It never runs every engine blindly: a creator seed gets the creator pipeline, a
domain gets the web intelligence engine, and a keyword is first resolved into an
entity (which requires a search provider — without one, NEXUS says exactly that
instead of guessing).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.omni.input_resolver import (KIND_CREATOR, KIND_KEYWORD, KIND_POST,
                                     KIND_WEBSITE, UniversalInput, classify)
from app.omni.keyless_web import resolve_official_site
from app.omni.webintel import Progress, WebIntelPayload, _noop, analyse as analyse_web

# Hosts that a keyword search may surface but that are never an entity's own website.
_NON_ENTITY_HOSTS = (
    "wikipedia.org", "linkedin.com", "facebook.com", "instagram.com", "youtube.com",
    "x.com", "twitter.com", "crunchbase.com", "glassdoor.", "indeed.", "amazon.",
    "flipkart.", "justdial.", "reddit.com", "quora.com", "medium.com", "github.com",
)


@dataclass
class PlanStep:
    engine: str
    reason: str


@dataclass
class Plan:
    kind: str
    seed: str
    steps: list[PlanStep] = field(default_factory=list)
    note: str = ""

    def describe(self) -> str:
        return " → ".join(s.engine for s in self.steps)


def plan(ui: UniversalInput) -> Plan:
    """Which engines run for this input, and why."""
    if ui.kind == KIND_POST:
        return Plan(kind=KIND_POST, seed=ui.value, steps=[
            PlanStep("media_fetch", "public HTML (+ YouTube oEmbed when it answers)"),
            PlanStep("metadata_extract", "title, author, VideoObject, no invented views"),
        ], note="Post/video public-metadata engine (app.omni.media).")
    if ui.kind == KIND_CREATOR:
        return Plan(kind=KIND_CREATOR, seed=ui.value, steps=[
            PlanStep("social_collection", f"{ui.platform} profile seed"),
            PlanStep("identity_expansion", "owned links, handle probes, keyless sources"),
            PlanStep("audience_inference", "signals + weighted rules"),
            PlanStep("content_analysis", "measured public performance"),
            PlanStep("agency_intelligence", "diligence metrics + media-buy scorecard"),
        ], note="Existing creator pipeline (app.engine.pipeline).")
    if ui.kind == KIND_WEBSITE:
        return Plan(kind=KIND_WEBSITE, seed=ui.value, steps=[
            PlanStep("web_crawl", f"bounded same-host crawl of {ui.domain}"),
            PlanStep("entity_extraction", "Organization schema, metadata, contacts"),
            PlanStep("tech_detection", "publicly served fingerprints"),
            PlanStep("social_discovery", "sameAs + outbound links, collected live"),
            PlanStep("product_intelligence", "JSON-LD offers, catalog ids and visible ₹ lines, not invented SKUs"),
            PlanStep("review_intelligence", "on-page JSON-LD Review bodies and printed AggregateRating, not G2"),
            PlanStep("award_intelligence", "on-site mentions vs curated award catalog"),
            PlanStep("competitor_discovery", "search-led official-site rivals"),
            PlanStep("market_intelligence", "search-led official-site market map"),
            PlanStep("seo_coverage", "present / thin / missing commercial paths"),
            PlanStep("indexability", "meta robots and X-Robots-Tag, not a ranking claim"),
            PlanStep("news_intelligence", "narrative radar from search, else Hacker News"),
            PlanStep("open_sources", "Archive.org, Wikipedia, Datamuse, Nominatim, REST Countries"),
            PlanStep("first_party_feeds", "RSS/Atom the homepage advertised"),
            PlanStep("site_signals", "robots.txt, well-known files, security headers"),
            PlanStep("ads_txt", "ads.txt / app-ads.txt records, not ad spend"),
            PlanStep("published_claims", "verification meta, rel=me and JSON-LD sameAs, never merge keys"),
            PlanStep("share_cards", "Open Graph / Twitter card / app-banner meta, not reach"),
            PlanStep("third_party_hosts", "off-host script and preconnect hosts, not spend"),
            PlanStep("document_links", "canonical / author / manifest / HTTP Link, not fetched"),
            PlanStep("csp_hosts", "CSP host tokens from the homepage header, not a live load list"),
            PlanStep("schema_inventory", "JSON-LD types, FAQ, jobs, events, articles, courses, ContactPoint, ItemList, AggregateOffer, OfferCatalog, speakable, WebPage lastReviewed, opening hours, HowTo tools, people, video, apps, NAP"),
            PlanStep("locale_inventory", "html lang, og:locale, Content-Language and same-host hreflang"),
            PlanStep("declared_surfaces", "app store, GitHub and status URLs the site linked"),
            PlanStep("legal_freshness", "privacy/terms dates from sampled policy pages"),
            PlanStep("printed_identity", "GSTIN/CIN/taxID and Organization logo the pages printed"),
            PlanStep("onpage_surfaces", "iframes, form actions, click-to-chat and linked PDFs"),
            PlanStep("website_scoring", "six scored dimensions with printed formulas"),
            PlanStep("predictive_intelligence",
                     "ORACLE + SIGNAL: snapshot trajectory, not demand"),
        ], note="Web intelligence engine (app.omni.webintel).")
    return Plan(kind=KIND_KEYWORD, seed=ui.value, steps=[
        PlanStep("entity_search", "resolve the text into an official website"),
        PlanStep("web_crawl", "then run the website plan against it"),
    ], note="Wikipedia / Wikidata / DuckDuckGo Instant Answer, then licensed search if a key is present.")


async def resolve_keyword(text: str) -> str:
    """Resolve free text into the entity's own website.

    Keyless sources run first so a free report still works. Licensed search
    is a fallback when those APIs do not name a first-party site.
    """
    from app.engine.discovery.search import search

    keyless = await resolve_official_site(text, _NON_ENTITY_HOSTS)
    if keyless:
        return keyless
    hits = await search(f'{text} official website', limit=8)
    for hit in hits:
        host = urlparse(hit.url).netloc.lower()
        if host and not any(b in host for b in _NON_ENTITY_HOSTS):
            return hit.url
    raise RuntimeError(
        f"No official website resolved for '{text}'. Wikipedia, Wikidata and "
        "DuckDuckGo Instant Answer did not name a first-party site, and licensed "
        "search was empty. Paste the exact URL instead.")


async def run_web(seed: str, report_id: str, *, progress: Progress = _noop,
                  collect_socials: bool = True) -> WebIntelPayload:
    """Execute the website plan (resolving a keyword first when needed)."""
    ui = classify(seed)
    if ui.kind == KIND_KEYWORD:
        progress("resolving entity via search", 3)
        target = await resolve_keyword(ui.value)
    elif ui.kind == KIND_WEBSITE:
        target = ui.value
    else:
        raise ValueError("run_web only handles website and keyword inputs; creator "
                         "seeds go through app.engine.pipeline")
    payload = await analyse_web(target, report_id, progress=progress,
                                collect_socials=collect_socials,
                                with_competitors=True)
    if ui.kind == KIND_KEYWORD:
        payload.warnings.insert(
            0, f"Entity resolved from the keyword '{ui.value}'; "
               f"verify {payload.domain} is the intended subject.")
    return payload
