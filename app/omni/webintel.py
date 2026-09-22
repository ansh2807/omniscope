"""Web Intelligence engine — the first OMNISCOPE engine beyond creators.

Given a domain, it crawls a bounded set of public pages through the compliant HTTP
layer, extracts what the site itself publishes, detects publicly observable
technologies, discovers the entity's social accounts (collected live by the existing
platform collectors), and produces a scored, evidence-backed website intelligence
payload.

Honesty contract, inherited from the creator engine:
  * every score prints its formula and inputs;
  * what was not measured is listed with the reason (no invented traffic, no
    fabricated performance metrics);
  * every page read becomes an evidence record with URL, hash and timestamp.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field
from selectolax.parser import HTMLParser

from app.config import settings
from app.engine.collectors.web import _jsonld, _meta, _same_as, _structured_products, _text
from app.engine.http import Fetched, fetch
from app.omni.evidence import EvidenceLog
from app.omni.ads import AdsIntel, summarise as summarise_ads
from app.omni.cards import analyse_cards
from app.omni.claims import analyse_claims
from app.omni.filings import collect_filings
from app.omni.identity import PrintedId, analyse_identity
from app.omni.keyless_web import official_ids_for_site
from app.omni.indexability import analyse_indexability
from app.omni.legal import analyse_legal
from app.omni.links import analyse_links
from app.omni.locale import analyse_locale
from app.omni.onpage import analyse_onpage
from app.omni.hosts import fetch_failure_copy, homepage_candidates
from app.omni.open_sources import collect as collect_open_sources
from app.omni.products import analyse_products
from app.omni.schema_intel import analyse_schema
from app.omni.site import (HeaderIntel, PublicIntel, collect_public_files,
                           from_headers, parse_robots)
from app.omni.surfaces import from_links as surfaces_from_links
from app.omni.vendors import analyse_vendors
from app.omni.content_dna import from_pages as content_dna_from_pages
from app.omni.desk import build_web_desk
from app.omni.reason import synthesize_web
from app.omni.risk import from_news as risk_from_news
from app.omni.usage import reset_search, search_calls

Progress = Callable[[str, int], None]

ENGINE_VERSION = "2.12.0"

# Pages worth crawling on a company site, in priority order.
PRIORITY_PATHS = re.compile(
    r"/(pricing|plans|products?|features|solutions|services|about(?:-us)?|company|"
    r"contact(?:-us)?|customers|case-stud|testimonials|press|news(?:room)?|blog|"
    r"resources|careers|team|faq|how-it-works|integrations|security|docs?)(?:[/_.-]|$)",
    re.I)

CTA_WORDS = re.compile(
    r"\b(sign\s?up|get started|start free|free trial|book a demo|request a demo|"
    r"buy now|add to cart|subscribe|contact sales|get a quote|try (?:it|for) free|"
    r"download|enrol|enroll|register)\b", re.I)

EMAIL_RE = re.compile(r"mailto:([^\"'?\s>]+)", re.I)
PHONE_RE = re.compile(r"tel:([+\d][\d\-().\s]{5,20})", re.I)
DATE_META = re.compile(
    r'(?:article:published_time|article:modified_time|datePublished|dateModified)"'
    r'\s*(?:content=|:)\s*"(\d{4}-\d{2}-\d{2})', re.I)

# Publicly observable technology fingerprints. Each is evidence the page itself serves
# to every visitor; nothing is probed beyond pages already fetched.
FINGERPRINTS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"wp-content|wp-includes", re.I), "WordPress", "CMS"),
    (re.compile(r"cdn\.shopify\.com|myshopify\.com", re.I), "Shopify", "Commerce"),
    (re.compile(r"/_next/static", re.I), "Next.js", "Framework"),
    (re.compile(r"/_nuxt/", re.I), "Nuxt", "Framework"),
    (re.compile(r"static\.parastorage\.com|wix\.com", re.I), "Wix", "Site builder"),
    (re.compile(r"squarespace\.com|squarespace-cdn", re.I), "Squarespace", "Site builder"),
    (re.compile(r"website-files\.com|webflow", re.I), "Webflow", "Site builder"),
    (re.compile(r"framerusercontent\.com", re.I), "Framer", "Site builder"),
    (re.compile(r"googletagmanager\.com", re.I), "Google Tag Manager", "Analytics"),
    (re.compile(r"google-analytics\.com|gtag\(", re.I), "Google Analytics", "Analytics"),
    (re.compile(r"connect\.facebook\.net", re.I), "Meta Pixel", "Analytics"),
    (re.compile(r"static\.hotjar\.com", re.I), "Hotjar", "Analytics"),
    (re.compile(r"clarity\.ms", re.I), "Microsoft Clarity", "Analytics"),
    (re.compile(r"js\.hs-scripts\.com|hubspot", re.I), "HubSpot", "Marketing"),
    (re.compile(r"intercom(?:cdn)?\.(?:io|com)", re.I), "Intercom", "Support"),
    (re.compile(r"crisp\.chat", re.I), "Crisp", "Support"),
    (re.compile(r"tawk\.to", re.I), "Tawk.to", "Support"),
    (re.compile(r"checkout\.razorpay\.com|razorpay\.com/v1", re.I), "Razorpay", "Payments"),
    (re.compile(r"js\.stripe\.com|checkout\.stripe\.com", re.I), "Stripe", "Payments"),
    (re.compile(r"paypal\.com/sdk", re.I), "PayPal", "Payments"),
    (re.compile(r"static\.klaviyo\.com", re.I), "Klaviyo", "Email marketing"),
    (re.compile(r"chimpstatic\.com|mailchimp\.com", re.I), "Mailchimp", "Email marketing"),
    (re.compile(r"cloudflareinsights\.com", re.I), "Cloudflare Analytics", "Analytics"),
]


# ------------------------------------------------------------------- models
class PageFacts(BaseModel):
    url: str
    title: str = ""
    meta_description: str = ""
    canonical: str = ""
    h1: list[str] = Field(default_factory=list)
    lang: str = ""
    viewport: bool = False
    word_count: int = 0
    internal_links: list[str] = Field(default_factory=list)
    external_links: list[str] = Field(default_factory=list)
    jsonld_types: list[str] = Field(default_factory=list)
    images: int = 0
    images_missing_alt: int = 0
    forms: int = 0
    cta_hits: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    dates_seen: list[str] = Field(default_factory=list)
    og: dict[str, str] = Field(default_factory=dict)


class TechDetection(BaseModel):
    name: str
    category: str
    evidence: str          # which fingerprint matched, on which page


class DimensionScore(BaseModel):
    key: str
    label: str
    score: float           # 0..10
    formula: str
    inputs: dict[str, object] = Field(default_factory=dict)
    unmeasured: list[str] = Field(default_factory=list)


class SocialPresence(BaseModel):
    platform: str
    url: str
    handle: str = ""
    display_name: str = ""
    followers: int | None = None
    verified: bool | None = None
    error: str = ""


class WebIntelPayload(BaseModel):
    report_id: str
    generated_at: datetime
    kind: str = "web"
    entity_name: str
    domain: str
    seed_url: str
    tagline: str = ""
    pages: list[PageFacts] = Field(default_factory=list)
    tech: list[TechDetection] = Field(default_factory=list)
    socials: list[SocialPresence] = Field(default_factory=list)
    products: list[dict] = Field(default_factory=list)
    product_intel: dict | None = None
    competitor_intel: dict | None = None
    award_intel: dict | None = None
    news_intel: dict | None = None
    feed_intel: dict | None = None
    review_intel: dict | None = None
    market_intel: dict | None = None
    seo_map: dict | None = None
    robots_intel: dict | None = None
    header_intel: dict | None = None
    public_intel: dict | None = None
    schema_intel: dict | None = None
    surface_intel: dict | None = None
    legal_intel: dict | None = None
    identity_intel: dict | None = None
    filings_intel: dict | None = None
    official_ids: dict = Field(default_factory=dict)
    onpage_intel: dict | None = None
    locale_intel: dict | None = None
    index_intel: dict | None = None
    ads_intel: dict | None = None
    claims_intel: dict | None = None
    card_intel: dict | None = None
    vendor_intel: dict | None = None
    link_intel: dict | None = None
    open_source_intel: dict | None = None
    trend_intel: dict | None = None
    reasoning: dict | None = None
    desk: dict | None = None
    content_dna: dict | None = None
    risk_intel: dict | None = None
    prediction: dict | None = None
    contacts: dict[str, list[str]] = Field(default_factory=dict)
    seo: dict[str, object] = Field(default_factory=dict)
    content: dict[str, object] = Field(default_factory=dict)
    scores: list[DimensionScore] = Field(default_factory=list)
    overall_score: float = 0.0
    opportunities: list[dict[str, str]] = Field(default_factory=list)
    unavailable: list[dict[str, str]] = Field(default_factory=list)
    evidence: EvidenceLog = Field(default_factory=EvidenceLog)
    warnings: list[str] = Field(default_factory=list)
    usage: dict[str, object] = Field(default_factory=dict)
    engine_version: str = ENGINE_VERSION


# ---------------------------------------------------------------- extraction
def extract_page(url: str, html: str) -> PageFacts:
    """Everything one public page states about itself. Pure function."""
    tree = HTMLParser(html)
    host = urlparse(url).netloc.lower().removeprefix("www.")

    title_node = tree.css_first("title")
    canonical_node = tree.css_first('link[rel="canonical"]')
    lang = (tree.css_first("html").attributes.get("lang") or "") if tree.css_first("html") else ""

    og: dict[str, str] = {}
    for key in ("og:site_name", "og:title", "og:description", "og:image", "og:type",
                "og:locale"):
        value = _meta(html, key)
        if value:
            og[key] = value

    internal, external = [], []
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(url, href).split("#")[0]
        link_host = urlparse(absolute).netloc.lower().removeprefix("www.")
        if not link_host:
            continue
        bucket = internal if link_host == host else external
        if absolute not in bucket:
            bucket.append(absolute)

    types: list[str] = []
    for entity in _jsonld(html):
        t = entity.get("@type")
        for name in ([t] if isinstance(t, str) else (t or [])):
            if isinstance(name, str) and name not in types:
                types.append(name)

    images = tree.css("img")
    body_text = _text(html)

    return PageFacts(
        url=url,
        title=(title_node.text(strip=True) if title_node else "")[:300],
        meta_description=(_meta(html, "description") or "")[:500],
        canonical=(canonical_node.attributes.get("href") or "") if canonical_node else "",
        h1=[h.text(strip=True)[:200] for h in tree.css("h1")][:5],
        lang=lang,
        viewport=bool(tree.css_first('meta[name="viewport"]')),
        word_count=len(body_text.split()),
        internal_links=internal[:150],
        external_links=external[:80],
        jsonld_types=types[:30],
        images=len(images),
        images_missing_alt=sum(1 for i in images if not (i.attributes.get("alt") or "").strip()),
        forms=len(tree.css("form")),
        cta_hits=list(dict.fromkeys(m.group(0).lower()
                                    for m in CTA_WORDS.finditer(body_text)))[:10],
        emails=list(dict.fromkeys(EMAIL_RE.findall(html)))[:10],
        phones=list(dict.fromkeys(p.strip() for p in PHONE_RE.findall(html)))[:5],
        dates_seen=list(dict.fromkeys(DATE_META.findall(html)))[:20],
        og=og,
    )


def detect_tech(pages: list[tuple[str, str]]) -> list[TechDetection]:
    """Technology fingerprints across fetched pages. Pure function."""
    found: dict[str, TechDetection] = {}
    for page_url, html in pages:
        for pattern, name, category in FINGERPRINTS:
            if name in found:
                continue
            m = pattern.search(html)
            if m:
                found[name] = TechDetection(
                    name=name, category=category,
                    evidence=f"'{m.group(0)[:60]}' served on {page_url}")
    return sorted(found.values(), key=lambda t: (t.category, t.name))


def entity_name_from(pages: list[PageFacts], html_home: str, domain: str) -> str:
    """Organization schema > og:site_name > homepage title > domain."""
    for entity in _jsonld(html_home):
        t = entity.get("@type")
        names = [t] if isinstance(t, str) else (t or [])
        if any(n in ("Organization", "Corporation", "LocalBusiness", "OnlineBusiness")
               for n in names if isinstance(n, str)):
            name = entity.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()[:120]
    if pages:
        og_name = pages[0].og.get("og:site_name")
        if og_name:
            return og_name.strip()[:120]
        if pages[0].title:
            return re.split(r"\s+[|\-–—]\s+", pages[0].title)[0].strip()[:120]
    return domain


# ------------------------------------------------------------------- scoring
def score_dimensions(pages: list[PageFacts], *, https: bool, robots_present: bool,
                     sitemap_present: bool, tech: list[TechDetection],
                     socials: list[SocialPresence], products: list[dict],
                     entity_name: str, domain: str) -> tuple[list[DimensionScore], float]:
    """Score what was actually observed. Every dimension prints its formula."""
    n = max(len(pages), 1)
    titled = sum(1 for p in pages if p.title)
    unique_titles = len({p.title for p in pages if p.title})
    described = sum(1 for p in pages if p.meta_description)
    h1d = sum(1 for p in pages if p.h1)
    canonicaled = sum(1 for p in pages if p.canonical)
    structured = sum(1 for p in pages if p.jsonld_types)
    og_covered = sum(1 for p in pages if p.og)
    viewport = sum(1 for p in pages if p.viewport)
    lang_set = sum(1 for p in pages if p.lang)
    words_total = sum(p.word_count for p in pages)
    substantive = sum(1 for p in pages if p.word_count >= 300)
    page_paths = " ".join(urlparse(p.url).path.lower() for p in pages)
    has_blog = bool(re.search(r"/(blog|resources|news|articles|insights)", page_paths))
    has_pricing = bool(re.search(r"/(pricing|plans)", page_paths))
    has_contact = bool(re.search(r"/contact", page_paths)) or any(p.emails or p.phones for p in pages)
    has_about = bool(re.search(r"/(about|company|team)", page_paths))
    has_privacy = any(re.search(r"privacy", u, re.I)
                      for p in pages for u in p.internal_links)
    has_terms = any(re.search(r"terms|tos\b", u, re.I)
                    for p in pages for u in p.internal_links)
    cta_pages = sum(1 for p in pages if p.cta_hits)
    form_pages = sum(1 for p in pages if p.forms)
    emails = sorted({e for p in pages for e in p.emails})
    phones = sorted({t for p in pages for t in p.phones})
    dates = sorted({d for p in pages for d in p.dates_seen})
    live_socials = [s for s in socials if not s.error]

    def clamp(x: float) -> float:
        return round(max(0.0, min(10.0, x)), 1)

    technical = DimensionScore(
        key="technical", label="Technical",
        score=clamp(2 * https + 2 * (viewport / n) + 2 * (canonicaled / n)
                    + 1 * robots_present + 2 * sitemap_present + 1 * (lang_set / n)),
        formula="2·https + 2·viewport_coverage + 2·canonical_coverage + 1·robots.txt "
                "+ 2·sitemap.xml + 1·lang_attribute_coverage",
        inputs={"https": https, "viewport_pages": viewport, "canonical_pages": canonicaled,
                "robots_txt": robots_present, "sitemap_xml": sitemap_present,
                "lang_pages": lang_set, "pages_sampled": n},
        unmeasured=["Core Web Vitals / page speed — needs lab or field measurement",
                    "server configuration beyond public responses"])

    seo = DimensionScore(
        key="seo", label="SEO",
        score=clamp(2 * (titled / n) + 1 * (unique_titles / max(titled, 1))
                    + 2 * (described / n) + 2 * (h1d / n) + 2 * (structured / n)
                    + 1 * (og_covered / n)),
        formula="2·title_coverage + 1·title_uniqueness + 2·meta_description_coverage "
                "+ 2·h1_coverage + 2·structured_data_coverage + 1·open_graph_coverage",
        inputs={"titled_pages": titled, "unique_titles": unique_titles,
                "described_pages": described, "h1_pages": h1d,
                "structured_data_pages": structured, "og_pages": og_covered,
                "pages_sampled": n},
        unmeasured=["rankings, search demand and traffic — need a search/keyword provider",
                    "backlink profile — needs a link-index provider"])

    content = DimensionScore(
        key="content", label="Content",
        score=clamp(3 * (substantive / n) + min(3.0, words_total / 4000)
                    + 2 * has_blog + 2 * min(1, len(dates))),
        formula="3·substantive_page_share(≥300 words) + min(3, total_words/4000) "
                "+ 2·blog_or_resources_present + 2·dated_content_present",
        inputs={"substantive_pages": substantive, "total_words": words_total,
                "blog_detected": has_blog, "dated_pages": len(dates),
                "latest_date_seen": dates[-1] if dates else None},
        unmeasured=["content performance (views, shares) — not published by websites"])

    brand = DimensionScore(
        key="brand", label="Brand",
        score=clamp(2 * (entity_name.lower() != domain.lower())
                    + 1 * any(p.meta_description for p in pages[:1])
                    + min(3.0, 1.0 * len(live_socials))
                    + 2 * any("Organization" in p.jsonld_types for p in pages)
                    + 2 * has_about),
        formula="2·named_entity + 1·homepage_description + min(3, 1·live_social_account) "
                "+ 2·organization_schema + 2·about_page",
        inputs={"entity_name": entity_name, "live_social_accounts": len(live_socials),
                "organization_schema": any("Organization" in p.jsonld_types for p in pages),
                "about_page": has_about},
        unmeasured=["brand awareness, recall and perception — need survey/panel data"])

    conversion = DimensionScore(
        key="conversion", label="Conversion",
        score=clamp(2 * has_pricing + 2 * min(1.0, cta_pages / n * 2)
                    + 2 * min(1.0, form_pages / n * 2) + 2 * has_contact
                    + 2 * min(1, len(products))),
        formula="2·pricing_page + 2·cta_coverage + 2·form_coverage + 2·contact_surface "
                "+ 2·structured_offers_present",
        inputs={"pricing_page": has_pricing, "cta_pages": cta_pages,
                "form_pages": form_pages, "contact_surface": has_contact,
                "structured_offers": len(products)},
        unmeasured=["conversion rate and funnel performance — first-party analytics only"])

    trust = DimensionScore(
        key="trust", label="Trust",
        score=clamp(2 * https + 2 * has_privacy + 1 * has_terms
                    + 2 * bool(emails or phones)
                    + 1 * any("PostalAddress" in p.jsonld_types for p in pages)
                    + 2 * min(1.0, sum(1 for s in live_socials if s.verified) or
                              (0.5 if live_socials else 0))),
        formula="2·https + 2·privacy_policy + 1·terms + 2·public_contact_channel "
                "+ 1·postal_address_schema + 2·verified_or_live_socials",
        inputs={"https": https, "privacy_policy": has_privacy, "terms": has_terms,
                "emails_found": len(emails), "phones_found": len(phones),
                "verified_socials": sum(1 for s in live_socials if s.verified)},
        unmeasured=["third-party review platforms — only on-page JSON-LD is read"])

    scores = [technical, seo, content, brand, conversion, trust]
    overall = round(sum(s.score for s in scores) / len(scores) * 10, 1)
    return scores, overall


def build_opportunities(scores: list[DimensionScore],
                        pages: list[PageFacts]) -> list[dict[str, str]]:
    """Rule-driven, each tied to a specific observation. No generic advice."""
    out: list[dict[str, str]] = []
    by_key = {s.key: s for s in scores}
    n = max(len(pages), 1)

    seo = by_key["seo"]
    if seo.inputs.get("described_pages", 0) < n:
        missing = n - int(seo.inputs["described_pages"])
        out.append({"title": "Add meta descriptions to uncovered pages",
                    "why": f"{missing} of {n} sampled pages have no meta description; "
                           "search engines will synthesise snippets instead.",
                    "evidence": "meta_description_coverage input in the SEO score"})
    if seo.inputs.get("structured_data_pages", 0) == 0:
        out.append({"title": "Publish structured data (JSON-LD)",
                    "why": "No sampled page serves Organization/Product/Article schema, "
                           "so rich results and entity linking are unavailable.",
                    "evidence": "structured_data_coverage input in the SEO score"})
    tech = by_key["technical"]
    if not tech.inputs.get("sitemap_xml"):
        out.append({"title": "Publish a sitemap.xml",
                    "why": "No sitemap was found at the conventional location; crawl "
                           "discovery depends entirely on internal links.",
                    "evidence": "sitemap.xml check in the Technical score"})
    conv = by_key["conversion"]
    if not conv.inputs.get("pricing_page"):
        out.append({"title": "Consider a public pricing or plans page",
                    "why": "No pricing/plans page was found in the sampled crawl. If "
                           "pricing is deliberately gated this is a strategy choice, "
                           "not an error.",
                    "evidence": "pricing_page input in the Conversion score"})
    trust = by_key["trust"]
    if not trust.inputs.get("privacy_policy"):
        out.append({"title": "Link a privacy policy from sampled pages",
                    "why": "No privacy link was observed; this affects trust and, "
                           "depending on jurisdiction, compliance.",
                    "evidence": "privacy_policy input in the Trust score"})
    brand = by_key["brand"]
    if brand.inputs.get("live_social_accounts", 0) == 0:
        out.append({"title": "Link social profiles from the website",
                    "why": "No social account could be discovered from the site's own "
                           "links or sameAs metadata.",
                    "evidence": "live_social_accounts input in the Brand score"})
    return out[:8]


LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
LASTMOD_RE = re.compile(r"<lastmod>\s*([^<\s]+)", re.I)
URL_BLOCK_RE = re.compile(r"<url\b[^>]*>(.*?)</url>", re.I | re.S)
SITEMAP_INDEX_RE = re.compile(r"<sitemapindex\b", re.I)


def sitemap_entries(xml: str, *, limit: int = 200) -> list[tuple[str, str]]:
    """(loc, lastmod-day) pairs. lastmod is YYYY-MM-DD or empty. Pure."""
    if not xml:
        return []
    out: list[tuple[str, str]] = []
    blocks = URL_BLOCK_RE.findall(xml)
    if blocks:
        for block in blocks:
            locs = LOC_RE.findall(block)
            if not locs:
                continue
            raw = LASTMOD_RE.search(block)
            day = (raw.group(1)[:10] if raw and raw.group(1)[:4].isdigit() else "")
            out.append((locs[0], day))
            if len(out) >= limit:
                return out
        return out
    for loc in LOC_RE.findall(xml)[:limit]:
        out.append((loc, ""))
    return out


def sitemap_locs(xml: str, *, limit: int = 200) -> list[str]:
    """URL inventory from a sitemap or sitemap index. Pure function."""
    return [loc for loc, _day in sitemap_entries(xml, limit=limit)]


def is_sitemap_index(xml: str) -> bool:
    return bool(xml and SITEMAP_INDEX_RE.search(xml))


def child_sitemaps(xml: str, domain: str, *, limit: int = 3) -> list[str]:
    """Same-host child sitemap URLs from an index. Off-host children are dropped."""
    if not is_sitemap_index(xml):
        return []
    host = domain.lower().removeprefix("www.")
    out: list[str] = []
    for link in sitemap_locs(xml, limit=40):
        if urlparse(link).netloc.lower().removeprefix("www.") != host:
            continue
        if link not in out:
            out.append(link)
        if len(out) >= limit:
            break
    return out


def crawl_frontier(domain: str, seed_url: str, home_links: list[str],
                   sitemap_urls: list[str], *, budget: int,
                   lastmods: dict[str, str] | None = None) -> list[str]:
    """Same-host crawl queue. Sitemap priority paths first, then homepage
    priority links, then other sitemap URLs (newer lastmod first). Never
    invents a path."""
    seed = seed_url.rstrip("/")
    host = domain.lower().removeprefix("www.")
    lastmods = lastmods or {}

    def same_host(link: str) -> bool:
        return urlparse(link).netloc.lower().removeprefix("www.") == host

    def usable(link: str) -> bool:
        return bool(link) and same_host(link) and link.rstrip("/") != seed

    sitemap_priority: list[str] = []
    sitemap_other: list[str] = []
    for link in sitemap_urls:
        if not usable(link):
            continue
        if PRIORITY_PATHS.search(urlparse(link).path):
            sitemap_priority.append(link)
        else:
            sitemap_other.append(link)
    sitemap_other.sort(key=lambda u: lastmods.get(u, ""), reverse=True)
    home_priority: list[str] = []
    for link in home_links:
        if not usable(link):
            continue
        if PRIORITY_PATHS.search(urlparse(link).path):
            home_priority.append(link)
    ordered: list[str] = []
    for bucket in (sitemap_priority, home_priority, sitemap_other):
        for link in bucket:
            if link not in ordered:
                ordered.append(link)
    return ordered[:max(budget, 0)]


# --------------------------------------------------------------- orchestrator
def _noop(stage: str, pct: int) -> None:  # pragma: no cover
    pass


async def analyse(seed_url: str, report_id: str, *, progress: Progress = _noop,
                  collect_socials: bool = True,
                  with_competitors: bool = True) -> WebIntelPayload:
    """Crawl → extract → detect → discover socials → score → evidence."""
    from app.omni.events import (ANALYSIS_COMPLETED, ANALYSIS_STARTED,
                                 CRAWL_COMPLETED, emit)

    url = seed_url if seed_url.startswith(("http://", "https://")) else f"https://{seed_url}"
    evidence = EvidenceLog()
    warnings: list[str] = []
    reset_search()
    robots_blocked = 0
    http_failed = 0
    emit(ANALYSIS_STARTED, seed=url, report_id=report_id)
    progress("fetching homepage", 5)

    home = Fetched(url=url, status=0, text="")
    for candidate in homepage_candidates(url):
        home = await fetch(candidate)
        if home.ok:
            url = candidate
            break

    domain = urlparse(url).netloc.lower().removeprefix("www.")
    if home.blocked_by_robots or not home.ok:
        warnings.append(fetch_failure_copy(
            domain, home.error or "", robots=home.blocked_by_robots))

    crawled = home.ok
    final = home.final_url or url
    parts = urlparse(final if "://" in final else f"https://{final}")
    domain = (parts.netloc or domain).lower().removeprefix("www.")
    base = f"{parts.scheme or 'https'}://{parts.netloc or domain}"
    https = (parts.scheme or "https") == "https"
    robots_present = False
    sitemap_present = False
    sitemap_urls: list[str] = []
    lastmods: dict[str, str] = {}
    robots_intel = parse_robots("")
    header_intel = HeaderIntel(assessed=False, reason="homepage was not fetched")
    home_facts = PageFacts(url=final)
    fetched_pages: list[tuple[str, Fetched]] = []
    pages: list[PageFacts] = []
    raw_html: list[tuple[str, str]] = []

    if crawled:
        evidence.add_fetch(home, "homepage content, metadata and link graph")
        progress("checking robots and sitemap", 12)
        robots = await fetch(f"{base}/robots.txt", check_robots=False)
        robots_present = robots.ok
        robots_intel = parse_robots(robots.text if robots.ok else "")
        header_intel = from_headers(home.headers, origin=domain)
        sitemap_candidates = [f"{base}/sitemap.xml"]
        if robots.ok:
            sitemap_candidates = (re.findall(r"(?im)^sitemap:\s*(\S+)", robots.text)
                                  or sitemap_candidates)
        sitemap = await fetch(sitemap_candidates[0], check_robots=False)
        sitemap_present = sitemap.ok and "<" in sitemap.text
        if sitemap_present:
            evidence.add_fetch(sitemap, "sitemap URL inventory")
            if is_sitemap_index(sitemap.text):
                for child_url in child_sitemaps(sitemap.text, domain):
                    child = await fetch(child_url, check_robots=False)
                    if not child.ok:
                        continue
                    for loc, day in sitemap_entries(child.text):
                        sitemap_urls.append(loc)
                        if day:
                            lastmods[loc] = day
                    evidence.add_fetch(child, "child sitemap URL inventory")
                sitemap_urls = sitemap_urls[:200]
            else:
                for loc, day in sitemap_entries(sitemap.text):
                    sitemap_urls.append(loc)
                    if day:
                        lastmods[loc] = day

        home_facts = extract_page(final, home.text)
        budget = max(settings.website_max_pages, 6) - 1
        candidates = crawl_frontier(
            domain, final, home_facts.internal_links, sitemap_urls, budget=budget,
            lastmods=lastmods)
        progress("crawling site pages", 25)
        responses = await asyncio.gather(*(fetch(u) for u in candidates),
                                         return_exceptions=True)

        fetched_pages = [(final, home)]
        for u, r in zip(candidates, responses):
            if isinstance(r, Exception):
                http_failed += 1
                continue
            if r.blocked_by_robots:
                robots_blocked += 1
                continue
            if not r.ok:
                http_failed += 1
                continue
            fetched_pages.append((r.final_url or u, r))
            evidence.add_fetch(r, "site page content and metadata")

        pages = [home_facts] + [extract_page(u, r.text) for u, r in fetched_pages[1:]]
        raw_html = [(u, r.text) for u, r in fetched_pages]
    else:
        progress("site unreachable — keyless sources", 25)
        if home.blocked_by_robots:
            robots = await fetch(f"{base}/robots.txt", check_robots=False)
            robots_present = robots.ok
            robots_intel = parse_robots(robots.text if robots.ok else "")

    emit(CRAWL_COMPLETED, domain=domain, pages=len(pages))
    progress("extracting entity and technologies", 45)

    tech = detect_tech(raw_html)
    entity_name = entity_name_from(pages, home.text, domain)

    progress("public files and schema", 48)
    if crawled:
        public_intel = await collect_public_files(base)
        ads_intel = summarise_ads(
            public_intel.ads, public_intel.ads_vars, public_intel.hits)
    else:
        public_intel = PublicIntel(
            assessed=False, reason="homepage was not fetched")
        ads_intel = AdsIntel(assessed=False, reason="homepage was not fetched")
    schema_intel = analyse_schema(raw_html)
    if public_intel.present_n:
        evidence.add(
            f"{public_intel.present_n} conventional public file(s)",
            base, method="http_get")
    if schema_intel.assessed:
        evidence.add(
            f"{len(schema_intel.types)} JSON-LD type(s)",
            final, method="jsonld")

    # products / offers from structured data across all pages
    products: list[dict] = []
    for u, html in raw_html:
        for product in _structured_products(_jsonld(html), u):
            row = product.model_dump()
            if row not in products:
                products.append(row)
    products = products[:30]

    # social discovery: sameAs metadata + external links, classified then collected live
    socials: list[SocialPresence] = []
    if collect_socials:
        progress("discovering social accounts", 55)
        from app.engine.discovery.expander import classify as classify_link
        from app.engine.pipeline import _collect_one

        seen_platforms: set[str] = set()
        social_targets: list[tuple[str, str]] = []
        link_pool = _same_as(_jsonld(home.text)) + [
            l for p in pages for l in p.external_links]
        for link in link_pool:
            platform = classify_link(link)
            if platform and platform not in seen_platforms and platform != "website":
                seen_platforms.add(platform)
                social_targets.append((platform, link))
        collected = await asyncio.gather(
            *(_collect_one(p, u) for p, u in social_targets[:5]),
            return_exceptions=True)
        for (platform, link), acc in zip(social_targets[:5], collected):
            if isinstance(acc, Exception) or acc is None:
                socials.append(SocialPresence(platform=platform, url=link,
                                              error="collection failed"))
                continue
            socials.append(SocialPresence(
                platform=acc.platform, url=acc.url, handle=acc.handle or "",
                display_name=acc.display_name or "", followers=acc.followers,
                verified=acc.verified,
                error="; ".join(acc.errors) if acc.errors and not acc.followers else ""))
            evidence.add(f"{acc.platform} account linked from the website",
                         acc.url, method="platform_collector")

    progress("first-party feeds", 76)
    from app.omni.feeds import analyse as analyse_feeds
    feed_intel = await analyse_feeds(final, home.text)
    if feed_intel.assessed and feed_intel.items:
        evidence.add(
            f"{len(feed_intel.items)} first-party feed item(s)",
            feed_intel.feeds[0] if feed_intel.feeds else final,
            method="rss_atom")

    progress("product intelligence", 78)
    product_intel = analyse_products(
        products, pages,
        tagline=home_facts.meta_description or home_facts.og.get("og:description", ""),
        raw_html=raw_html)

    surface_pool = _same_as(_jsonld(home.text))
    for page_url, html in raw_html[1:]:
        surface_pool.extend(_same_as(_jsonld(html)))
    for page in pages:
        surface_pool.extend(page.external_links)
        surface_pool.extend(page.internal_links)
    surface_intel = surfaces_from_links(surface_pool)
    if surface_intel.links:
        evidence.add(
            f"{len(surface_intel.links)} declared surface link(s)",
            surface_intel.links[0].url, method="outbound_link")

    progress("legal and identity prints", 80)
    legal_intel = analyse_legal(raw_html)
    identity_intel = analyse_identity(raw_html)
    if legal_intel.assessed and legal_intel.latest_updated:
        evidence.add(
            f"policy page dated {legal_intel.latest_updated}",
            legal_intel.policies[0].url, method="html_text")
    if identity_intel.assessed and identity_intel.ids:
        evidence.add(
            f"{len(identity_intel.ids)} printed identifier(s)",
            identity_intel.ids[0].url or final, method="html_text")

    wd_ids = await official_ids_for_site(entity_name, domain)
    official_ids = dict(wd_ids.get("official_ids") or {})
    if official_ids:
        seen_ids = {(row.kind, row.value) for row in identity_intel.ids}
        for kind, value in official_ids.items():
            key = (kind, str(value))
            if key in seen_ids:
                continue
            seen_ids.add(key)
            identity_intel.ids.append(PrintedId(
                kind=kind, value=str(value), source="wikidata",
                url=str((wd_ids.get("official_id_urls") or {}).get(kind) or "")))
        identity_intel.assessed = True
    filings_intel = await collect_filings(identity_intel.ids, official_ids)
    if filings_intel.assessed and filings_intel.records:
        evidence.add(
            f"{len(filings_intel.records)} official filing record(s)",
            filings_intel.records[0].official_url or final, method="official_api")

    onpage_intel = analyse_onpage(raw_html)
    if onpage_intel.hits:
        evidence.add(
            f"{len(onpage_intel.hits)} on-page embed/form/pdf/chat surface(s)",
            onpage_intel.hits[0].page or final, method="html_dom")

    home_headers = home.headers or {}
    locale_intel = analyse_locale(
        pages,
        hreflang=schema_intel.hreflang,
        content_language=home_headers.get("content-language") or "",
    )
    if locale_intel.langs or locale_intel.og_locales or locale_intel.hreflang:
        evidence.add(
            "locale tag(s) " + ", ".join(
                (locale_intel.langs + locale_intel.og_locales + locale_intel.hreflang)[:6]),
            final, method="html_dom")

    index_intel = analyse_indexability(raw_html, home.headers)
    if index_intel.noindex:
        evidence.add(
            f"{len(index_intel.noindex)} page(s) printed noindex",
            index_intel.noindex[0], method="html_dom")
    if header_intel.last_modified:
        evidence.add(
            f"Last-Modified {header_intel.last_modified}",
            final, method="http_header")

    claims_intel = analyse_claims(raw_html)
    if ads_intel.rows:
        evidence.add(
            f"{len(ads_intel.rows)} ads.txt record(s)",
            f"{base}{ads_intel.files[0]}" if ads_intel.files else base,
            method="http_get")
    if claims_intel.verifications:
        evidence.add(
            "verification meta: " + ", ".join(claims_intel.verifications),
            final, method="html_dom")
    if claims_intel.rel_me:
        evidence.add(
            f"{len(claims_intel.rel_me)} rel=me link(s)",
            claims_intel.rel_me[0].url, method="html_dom")
    if claims_intel.same_as:
        evidence.add(
            f"{len(claims_intel.same_as)} sameAs URL(s) printed",
            claims_intel.same_as[0].url, method="json_ld")

    card_intel = analyse_cards(raw_html)
    vendor_intel = analyse_vendors(raw_html)
    link_intel = analyse_links(raw_html, home.headers)
    if card_intel.twitter_site or card_intel.og_type:
        evidence.add(
            "share card " + " ".join(
                x for x in (card_intel.og_type, card_intel.twitter_site) if x),
            final, method="html_dom")
    if vendor_intel.unique:
        evidence.add(
            f"{len(vendor_intel.unique)} off-host script/resource host(s)",
            vendor_intel.hosts[0].url or final, method="html_dom")
    if link_intel.canonical or link_intel.manifests:
        evidence.add(
            "document link " + (link_intel.canonical or link_intel.manifests[0]),
            link_intel.canonical or link_intel.manifests[0], method="html_dom")
    if header_intel.csp_hosts:
        evidence.add(
            f"{len(header_intel.csp_hosts)} CSP host token(s)",
            final, method="http_header")

    progress("award intelligence", 82)
    from app.omni.awards import analyse_awards
    award_intel = analyse_awards(raw_html)

    competitor_intel = None
    if with_competitors:
        progress("discovering competitors", 84)
        from app.omni.competitors import discover as discover_company_competitors
        competitor_intel = await discover_company_competitors(entity_name, domain)
        if competitor_intel.assessed and competitor_intel.competitors:
            evidence.add(
                f"{len(competitor_intel.competitors)} competitor website(s) from search",
                competitor_intel.query_used or "search", method="search_api")

    progress("review intelligence", 85)
    from app.omni.reviews import analyse_reviews
    review_intel = analyse_reviews(raw_html, products)
    if review_intel.ratings:
        evidence.add(
            f"{len(review_intel.ratings)} AggregateRating node(s) printed",
            domain, method="jsonld")
    if review_intel.item_count:
        evidence.add(
            f"{review_intel.item_count} on-page review(s)",
            domain, method="jsonld")

    progress("seo coverage map", 86)
    from app.omni.seo_map import coverage_map
    seo_map = coverage_map(pages, sitemap_urls)

    progress("market map", 87)
    from app.omni.market import scan as scan_market
    market_intel = await scan_market(entity_name, domain)
    if market_intel.assessed:
        evidence.add(
            f"{len(market_intel.participants)} market participant(s)",
            market_intel.query_used or "search", method="search_api")

    progress("narrative radar", 88)
    from app.omni.news import scan as scan_news
    news_intel = await scan_news(entity_name, domain)
    if news_intel.assessed:
        evidence.add(
            f"{len(news_intel.items)} news/search item(s)",
            news_intel.query_used or "search", method="search_api")

    progress("open public sources", 89)
    address = schema_intel.nap.address if schema_intel.nap else ""
    open_source_intel = await collect_open_sources(
        entity_name, domain, address=address)
    if open_source_intel.assessed:
        evidence.add(
            "keyless public-api records (Archive.org / Wikipedia / Datamuse)",
            domain, method="public_api")

    progress("scoring", 90)
    scores, overall = score_dimensions(
        pages, https=https, robots_present=robots_present,
        sitemap_present=sitemap_present, tech=tech, socials=socials,
        products=products, entity_name=entity_name, domain=domain)

    emails = sorted({e for p in pages for e in p.emails})
    phones = sorted({t for p in pages for t in p.phones})
    if schema_intel.nap:
        if schema_intel.nap.email and schema_intel.nap.email not in emails:
            emails.append(schema_intel.nap.email)
            emails.sort()
        if schema_intel.nap.telephone and schema_intel.nap.telephone not in phones:
            phones.append(schema_intel.nap.telephone)
            phones.sort()
    dates = sorted({d for p in pages for d in p.dates_seen})
    feed_dates = [i.published for i in feed_intel.items if i.published]
    article_dates = [a.published for a in schema_intel.articles if a.published]
    article_dates += [a.modified for a in schema_intel.articles if a.modified]
    article_dates += [p.last_reviewed for p in schema_intel.web_pages if p.last_reviewed]
    course_dates = [c.start for c in schema_intel.courses if c.start]
    video_dates = [v.uploaded for v in schema_intel.videos if v.uploaded]
    legal_dates = [p.updated for p in legal_intel.policies if p.updated]
    dated = sorted({*dates, *feed_dates, *article_dates, *course_dates,
                    *video_dates, *legal_dates})

    unavailable = [
        {"item": "Traffic, unique visitors, engagement",
         "why": "First-party analytics; no external tool measures this honestly."},
        {"item": "Search rankings and keyword demand",
         "why": "The SEO map is coverage (present/thin/missing), not demand × competition."},
        {"item": "Page speed / Core Web Vitals",
         "why": "Needs lab or field performance measurement, not static HTML."},
        {"item": "Revenue, conversion rates",
         "why": "Private commercial data."},
        {"item": "Market share and win/loss vs competitors",
         "why": "Not published by websites; search only surfaces candidate names."},
        {"item": "Award wins verified by the awarding body",
         "why": "On-site claims stay self-claimed until the official listing is fetched."},
        {"item": "This year's award deadlines",
         "why": "The calendar lists typical seasons from a curated catalog, not live dates."},
        {"item": "Traffic, ranking or revenue forecasts",
         "why": "ORACLE only compares stored snapshots of what this engine measured."},
    ]
    if competitor_intel is not None and not competitor_intel.assessed:
        unavailable.append({
            "item": "Company competitor list",
            "why": competitor_intel.reason,
        })
    if not news_intel.assessed:
        unavailable.append({
            "item": "News / narrative radar",
            "why": news_intel.reason,
        })
    if not open_source_intel.assessed:
        unavailable.append({
            "item": "Keyless public APIs",
            "why": open_source_intel.reason,
        })
    if not review_intel.assessed:
        unavailable.append({
            "item": "On-page reviews",
            "why": review_intel.reason,
        })
    if not market_intel.assessed:
        unavailable.append({
            "item": "Market participant map",
            "why": market_intel.reason,
        })
    if not feed_intel.assessed:
        unavailable.append({
            "item": "First-party RSS/Atom feed",
            "why": feed_intel.reason,
        })
    if not schema_intel.assessed:
        unavailable.append({
            "item": "JSON-LD schema inventory",
            "why": schema_intel.reason,
        })
    if not robots_intel.assessed:
        unavailable.append({
            "item": "robots.txt directives",
            "why": robots_intel.reason,
        })
    if not legal_intel.assessed:
        unavailable.append({
            "item": "Legal / policy revision dates",
            "why": legal_intel.reason,
        })
    if not identity_intel.assessed:
        unavailable.append({
            "item": "Printed business identifiers",
            "why": identity_intel.reason,
        })
    if not filings_intel.assessed:
        unavailable.append({
            "item": "Official filings (SEC / GLEIF / MCA)",
            "why": filings_intel.reason,
        })
    if crawled and len(pages) < 3:
        warnings.append(f"Only {len(pages)} page(s) could be crawled; scores describe "
                        "a small sample of the site.")

    progress("assembling payload", 92)
    payload = WebIntelPayload(
        report_id=report_id,
        generated_at=datetime.now(timezone.utc),
        entity_name=entity_name,
        domain=domain,
        seed_url=seed_url,
        tagline=home_facts.meta_description or home_facts.og.get("og:description", ""),
        pages=pages,
        tech=tech,
        socials=socials,
        products=products,
        product_intel=product_intel.model_dump(),
        competitor_intel=competitor_intel.model_dump() if competitor_intel else None,
        award_intel=award_intel.model_dump(),
        news_intel=news_intel.model_dump(),
        open_source_intel=open_source_intel.model_dump(),
        feed_intel=feed_intel.model_dump(),
        review_intel=review_intel.model_dump(),
        market_intel=market_intel.model_dump(),
        seo_map=seo_map.model_dump(),
        robots_intel=robots_intel.model_dump(),
        header_intel=header_intel.model_dump(),
        public_intel=public_intel.model_dump(),
        schema_intel=schema_intel.model_dump(),
        surface_intel=surface_intel.model_dump(),
        legal_intel=legal_intel.model_dump(),
        identity_intel=identity_intel.model_dump(),
        filings_intel=filings_intel.model_dump(),
        official_ids=official_ids,
        onpage_intel=onpage_intel.model_dump(),
        locale_intel=locale_intel.model_dump(),
        index_intel=index_intel.model_dump(),
        ads_intel=ads_intel.model_dump(),
        claims_intel=claims_intel.model_dump(),
        card_intel=card_intel.model_dump(),
        vendor_intel=vendor_intel.model_dump(),
        link_intel=link_intel.model_dump(),
        contacts={"emails": emails, "phones": phones},
        seo={
            "robots_txt": robots_present,
            "sitemap_xml": sitemap_present,
            "sitemap_url_count": len(sitemap_urls),
            "structured_data_types": sorted({t for p in pages for t in p.jsonld_types}),
        },
        content={
            "pages_sampled": len(pages),
            "total_words": sum(p.word_count for p in pages),
            "latest_dated_content": dated[-1] if dated else None,
        },
        scores=scores,
        overall_score=overall,
        opportunities=build_opportunities(scores, pages),
        unavailable=unavailable,
        evidence=evidence,
        warnings=warnings,
        usage={
            "pages_sampled": len(pages),
            "http_ok": len(fetched_pages),
            "robots_blocked": robots_blocked,
            "http_failed": http_failed,
            "search_calls": search_calls(),
            "search_used": search_calls() > 0,
            "methods": (["http_get"] +
                        (["search_ensemble"] if search_calls() else [])),
            "note": ("Counts are this run's public fetches and licensed search "
                     "calls. Not a billing invoice and not estimated API spend."),
        },
    )
    payload.content_dna = content_dna_from_pages(pages).model_dump()
    payload.risk_intel = risk_from_news(news_intel.model_dump()).model_dump()
    payload.reasoning = synthesize_web(
        scores=scores, opportunities=payload.opportunities,
        unavailable=unavailable, seo_map=seo_map.model_dump(),
        review_intel=review_intel.model_dump(),
        competitor_intel=competitor_intel.model_dump() if competitor_intel else None,
        overall=overall,
        feed_intel=feed_intel.model_dump(),
        schema_intel=schema_intel.model_dump(),
        surface_intel=surface_intel.model_dump(),
        legal_intel=legal_intel.model_dump(),
        identity_intel=identity_intel.model_dump(),
        onpage_intel=onpage_intel.model_dump(),
        locale_intel=locale_intel.model_dump(),
        index_intel=index_intel.model_dump(),
        product_intel=product_intel.model_dump(),
        ads_intel=ads_intel.model_dump(),
        claims_intel=claims_intel.model_dump(),
        card_intel=card_intel.model_dump(),
        vendor_intel=vendor_intel.model_dump(),
        link_intel=link_intel.model_dump(),
        header_intel=header_intel.model_dump(),
    ).model_dump()
    payload.desk = build_web_desk(payload).model_dump()
    emit(ANALYSIS_COMPLETED, report_id=report_id, domain=domain, score=overall)
    return payload
