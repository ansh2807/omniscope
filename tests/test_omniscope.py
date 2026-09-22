"""OMNISCOPE layer: universal input, NEXUS planning, web intelligence, registry.

Everything here is offline — extraction and scoring are pure functions over fixture
HTML, and no test touches the network.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.omni import registry as reg
from app.omni.input_resolver import (KIND_CREATOR, KIND_KEYWORD, KIND_POST,
                                     KIND_WEBSITE, classify)
from app.omni.nexus import plan
from app.omni.webintel import (DimensionScore, SocialPresence, WebIntelPayload,
                               build_opportunities, detect_tech, entity_name_from,
                               extract_page, score_dimensions)

FIXTURE_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<title>Acme Analytics — Product Intelligence for Teams</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Acme turns product data into decisions.">
<meta property="og:site_name" content="Acme Analytics">
<link rel="canonical" href="https://acme.example/">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Organization","name":"Acme Analytics Pvt Ltd",
 "sameAs":["https://www.youtube.com/@acme","https://x.com/acme"]}
</script>
<script type="application/ld+json">
{"@type":"Product","name":"Acme Pro","offers":{"price":"4999","priceCurrency":"INR","url":"https://acme.example/pricing"}}
</script>
<script src="https://www.googletagmanager.com/gtm.js?id=GTM-XXXX"></script>
</head><body>
<h1>Product intelligence for growing teams</h1>
<p>Start free trial today. Book a demo with our team.</p>
<img src="/hero.png" alt="dashboard"><img src="/logo.png">
<form action="/signup"><input type="email"></form>
<a href="/pricing">Pricing</a>
<a href="/about">About us</a>
<a href="/privacy">Privacy policy</a>
<a href="https://www.youtube.com/@acme">YouTube</a>
<a href="mailto:hello@acme.example">hello@acme.example</a>
<a href="tel:+911234567890">Call us</a>
<p>""" + ("word " * 400) + """</p>
</body></html>"""

WP_HTML = '<html><head><link href="/wp-content/themes/x/style.css"></head><body></body></html>'


# ------------------------------------------------------------ input resolver
@pytest.mark.parametrize("raw,kind", [
    ("https://www.instagram.com/democreator/", KIND_CREATOR),
    ("https://www.youtube.com/@acme", KIND_CREATOR),
    ("@democreator", KIND_CREATOR),
    ("democreator", KIND_CREATOR),                 # bare handle keeps legacy behaviour
    ("https://topmate.io/someone", KIND_CREATOR),
    ("acme.com", KIND_WEBSITE),
    ("https://acme.com/pricing", KIND_WEBSITE),
    ("www.acme.co.in", KIND_WEBSITE),
    ("crm software india", KIND_KEYWORD),
    ("Acme Software", KIND_KEYWORD),
    ("https://www.instagram.com/p/AbC123/", KIND_POST),
    ("https://www.youtube.com/watch?v=dQw4w9wgWcQ", KIND_POST),
    ("https://x.com/acme/status/1234567890", KIND_POST),
    ("https://www.reddit.com/r/saas/comments/abc123/launch/", KIND_POST),
    ("https://bsky.app/profile/alice.bsky.social/post/3kabc", KIND_POST),
    ("https://www.tiktok.com/@acme/video/1234567890", KIND_POST),
])
def test_classify_kinds(raw, kind):
    assert classify(raw).kind == kind


def test_classify_creator_carries_platform_and_handle():
    ui = classify("https://www.instagram.com/democreator/")
    assert ui.platform == "instagram" and ui.handle == "democreator"


def test_classify_website_carries_domain():
    ui = classify("https://www.acme.com/pricing")
    assert ui.domain == "acme.com"


def test_classify_empty_raises():
    with pytest.raises(ValueError):
        classify("   ")


# ------------------------------------------------------------------- planner
def test_plan_selects_engines_by_kind():
    creator = plan(classify("@handle"))
    website = plan(classify("acme.com"))
    keyword = plan(classify("acme software pricing"))
    assert creator.kind == KIND_CREATOR
    assert any(s.engine == "social_collection" for s in creator.steps)
    assert not any(s.engine == "web_crawl" for s in creator.steps)
    assert website.kind == KIND_WEBSITE
    assert any(s.engine == "web_crawl" for s in website.steps)
    assert any(s.engine == "product_intelligence" for s in website.steps)
    assert any(s.engine == "award_intelligence" for s in website.steps)
    assert any(s.engine == "competitor_discovery" for s in website.steps)
    assert any(s.engine == "news_intelligence" for s in website.steps)
    assert any(s.engine == "open_sources" for s in website.steps)
    assert any(s.engine == "first_party_feeds" for s in website.steps)
    assert any(s.engine == "site_signals" for s in website.steps)
    assert any(s.engine == "schema_inventory" for s in website.steps)
    assert any(s.engine == "declared_surfaces" for s in website.steps)
    assert any(s.engine == "legal_freshness" for s in website.steps)
    assert any(s.engine == "printed_identity" for s in website.steps)
    assert any(s.engine == "onpage_surfaces" for s in website.steps)
    assert any(s.engine == "locale_inventory" for s in website.steps)
    assert any(s.engine == "indexability" for s in website.steps)
    assert any(s.engine == "ads_txt" for s in website.steps)
    assert any(s.engine == "published_claims" for s in website.steps)
    assert any(s.engine == "share_cards" for s in website.steps)
    assert any(s.engine == "third_party_hosts" for s in website.steps)
    assert any(s.engine == "document_links" for s in website.steps)
    assert any(s.engine == "csp_hosts" for s in website.steps)
    assert any(s.engine == "review_intelligence" for s in website.steps)
    assert any(s.engine == "market_intelligence" for s in website.steps)
    assert any(s.engine == "seo_coverage" for s in website.steps)
    assert any(s.engine == "predictive_intelligence" for s in website.steps)
    assert any(s.engine == "website_scoring" for s in website.steps)
    assert keyword.steps[0].engine == "entity_search"
    post = plan(classify("https://www.instagram.com/p/AbC123/"))
    assert post.kind == KIND_POST
    assert any(s.engine == "media_fetch" for s in post.steps)


# ---------------------------------------------------------------- extraction
def test_extract_page_reads_what_the_page_states():
    p = extract_page("https://acme.example/", FIXTURE_HTML)
    assert p.title.startswith("Acme Analytics")
    assert p.meta_description == "Acme turns product data into decisions."
    assert p.canonical == "https://acme.example/"
    assert p.h1 == ["Product intelligence for growing teams"]
    assert p.lang == "en"
    assert p.viewport is True
    assert p.word_count > 400
    assert "https://acme.example/pricing" in p.internal_links
    assert any("youtube.com" in u for u in p.external_links)
    assert "Organization" in p.jsonld_types and "Product" in p.jsonld_types
    assert p.images == 2 and p.images_missing_alt == 1
    assert p.forms == 1
    assert "free trial" in " ".join(p.cta_hits) or "book a demo" in " ".join(p.cta_hits)
    assert p.emails == ["hello@acme.example"]
    assert p.phones and p.phones[0].startswith("+91")


def test_detect_tech_names_evidence():
    tech = detect_tech([("https://acme.example/", FIXTURE_HTML),
                        ("https://blog.example/", WP_HTML)])
    names = {t.name for t in tech}
    assert "Google Tag Manager" in names and "WordPress" in names
    assert all(t.evidence for t in tech)


def test_entity_name_prefers_organization_schema():
    pages = [extract_page("https://acme.example/", FIXTURE_HTML)]
    assert entity_name_from(pages, FIXTURE_HTML, "acme.example") == "Acme Analytics Pvt Ltd"


def test_entity_name_falls_back_to_domain():
    assert entity_name_from([], "<html></html>", "plain.example") == "plain.example"


# ------------------------------------------------------------------- scoring
def _scored(socials=()):
    pages = [extract_page("https://acme.example/", FIXTURE_HTML)]
    return score_dimensions(
        pages, https=True, robots_present=True, sitemap_present=True,
        tech=detect_tech([("https://acme.example/", FIXTURE_HTML)]),
        socials=list(socials), products=[{"name": "Acme Pro"}],
        entity_name="Acme Analytics Pvt Ltd", domain="acme.example")


def test_scores_are_bounded_and_explained():
    scores, overall = _scored()
    assert len(scores) == 6
    for s in scores:
        assert 0.0 <= s.score <= 10.0, s.key
        assert s.formula and s.inputs, s.key
    assert 0.0 <= overall <= 100.0


def test_scores_reward_observed_fundamentals():
    scores, overall = _scored(socials=[SocialPresence(
        platform="youtube", url="https://youtube.com/@acme", followers=1000)])
    by_key = {s.key: s for s in scores}
    assert by_key["technical"].score >= 8       # https+viewport+canonical+robots+sitemap+lang
    assert by_key["trust"].inputs["privacy_policy"] is True
    assert overall > 50


def test_unmeasured_items_are_declared_not_scored():
    scores, _ = _scored()
    tech = next(s for s in scores if s.key == "technical")
    assert any("Core Web Vitals" in u for u in tech.unmeasured)
    seo = next(s for s in scores if s.key == "seo")
    assert any("provider" in u for u in seo.unmeasured)


def test_opportunities_fire_on_specific_gaps():
    bare = extract_page("https://bare.example/", "<html><body><p>hi</p></body></html>")
    scores, _ = score_dimensions(
        [bare], https=False, robots_present=False, sitemap_present=False,
        tech=[], socials=[], products=[], entity_name="bare.example",
        domain="bare.example")
    opps = build_opportunities(scores, [bare])
    titles = " ".join(o["title"] for o in opps)
    assert "meta description" in titles.lower()
    assert "sitemap" in titles.lower()
    assert all(o.get("evidence") for o in opps)


# ------------------------------------------------------- product / competitor
def test_product_battlecard_from_structured_offers():
    from app.omni.products import analyse_products
    pages = [extract_page("https://acme.example/pricing", FIXTURE_HTML)]
    intel = analyse_products(
        [{"name": "Acme Pro", "kind": "product", "price_inr": 4999.0},
         {"name": "Acme Starter", "kind": "product", "price_inr": 999.0}],
        pages, tagline="Acme turns product data into decisions.")
    assert intel.assessed is True
    assert intel.pricing_model in {"paid", "mixed"}
    assert intel.price_floor == 999.0 and intel.price_ceiling == 4999.0
    assert intel.offer_count == 2
    assert "4999" in intel.positioning or "9,999" in intel.positioning or "999" in intel.positioning


def test_product_intel_honest_when_nothing_published():
    from app.omni.products import analyse_products
    bare = extract_page("https://bare.example/", "<html><body><p>hi</p></body></html>")
    intel = analyse_products([], [bare])
    assert intel.assessed is False
    assert "No Product" in intel.reason_not_assessed


def test_pick_competitors_drops_directories_and_self():
    from app.omni.competitors import pick_competitors
    from app.schemas import SearchHit
    hits = [
        SearchHit(query="Acme alternatives", title="Acme — Home",
                  url="https://www.acme.example/", snippet="self"),
        SearchHit(query="Acme alternatives", title="Acme vs rivals — G2",
                  url="https://www.g2.com/products/acme", snippet="directory"),
        SearchHit(query="Acme alternatives", title="Northwind Analytics",
                  url="https://northwind.io/", snippet="BI for teams"),
        SearchHit(query="Acme alternatives", title="Contoso",
                  url="https://contoso.com/pricing", snippet="enterprise CRM"),
    ]
    rivals = pick_competitors(hits, "acme.example", limit=5)
    domains = [r.domain for r in rivals]
    assert "northwind.io" in domains and "contoso.com" in domains
    assert "g2.com" not in domains and "acme.example" not in domains


# ------------------------------------------------------------------ awards
def test_awards_self_claimed_from_own_page():
    from app.omni.awards import analyse_awards
    html = "<html><body><p>We won a Cannes Lions Gold in 2024 for the launch film.</p></body></html>"
    intel = analyse_awards([("https://acme.example/about", html)])
    assert intel.assessed is True
    assert intel.mentions[0].award == "Cannes Lions"
    assert intel.mentions[0].status == "self_claimed"
    assert any(c.mentioned_on_site for c in intel.calendar if c.name == "Cannes Lions")


def test_awards_absent_is_honest_not_a_loss():
    from app.omni.awards import analyse_awards
    intel = analyse_awards([("https://acme.example/", "<html><body><p>Hello</p></body></html>")])
    assert intel.assessed is True
    assert intel.mentions == []
    assert "never won" in intel.reason.lower()


def test_entity_upsert_updates_same_domain():
    from sqlmodel import Session, SQLModel, create_engine, select

    from app.models import Entity, EvidenceItem
    from app.omni.evidence import EvidenceLog
    from app.omni.graph import upsert_from_web

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    pages = [extract_page("https://acme.example/", FIXTURE_HTML)]
    scores, overall = _scored()
    log = EvidenceLog()
    log.add("homepage", "https://acme.example/", method="http_get")
    payload = WebIntelPayload(
        report_id="aaaaaaaaaaaa", generated_at=datetime.now(timezone.utc),
        entity_name="Acme Analytics Pvt Ltd", domain="acme.example",
        seed_url="https://acme.example/", scores=scores, overall_score=overall,
        pages=pages, evidence=log)
    with Session(engine) as s:
        first = upsert_from_web(s, payload, org_id=None, report_id="aaaaaaaaaaaa")
        first_id = first.id
        assert first.watched is True
    payload.overall_score = 71.0
    payload.report_id = "bbbbbbbbbbbb"
    with Session(engine) as s:
        second = upsert_from_web(s, payload, org_id=None, report_id="bbbbbbbbbbbb")
        assert second.id == first_id
        assert second.last_score == 71.0
        assert s.exec(select(Entity)).all().__len__() == 1
        assert len(s.exec(select(EvidenceItem)).all()) == 1


# -------------------------------------------------------------- news / events
def test_narrative_classifier_is_keyword_not_reach():
    from app.omni.news import classify_item, from_hits
    from app.schemas import SearchHit
    assert classify_item("Acme raises Series B", "funding round") == "growth"
    assert classify_item("Acme unveils new plan", "pricing update") == "product"
    assert classify_item("Picnic photos", "sunny day") == "other"
    empty = from_hits([], "acme news")
    assert empty.assessed is False
    hits = [SearchHit(query="acme news", title="Acme sued over ads",
                      url="https://news.example/sued", snippet="lawsuit filed")]
    intel = from_hits(hits, "acme news")
    assert intel.assessed is True
    assert intel.items[0].narrative == "crisis"
    assert intel.narratives.get("crisis") == 1
    assert intel.items[0].source_host == "news.example"


def test_article_extract_and_reclassify_from_page():
    from app.omni.news import NewsItem, apply_article, extract_article, skip_host
    html = """<html><head>
    <meta property="og:title" content="Regulator files lawsuit">
    <meta property="article:published_time" content="2026-06-15T08:00:00Z">
    <meta property="og:description" content="A lawsuit was filed this morning.">
    </head><body><p>Details later.</p></body></html>"""
    facts = extract_article("https://news.example/acme", html)
    assert facts.published.startswith("2026-06-15")
    assert facts.source_host == "news.example"
    item = NewsItem(title="https://news.example/acme", url="https://news.example/acme",
                    snippet="company update", narrative="other")
    apply_article(item, facts)
    assert item.page_status == "fetched"
    assert item.narrative == "crisis"
    assert item.title == "Regulator files lawsuit"
    assert skip_host("https://www.youtube.com/watch?v=x") is True
    assert skip_host("https://news.example/a") is False


def test_reddit_json_is_listing_not_reach():
    from app.omni.media import from_reddit_json, platform_of, reddit_json_url
    assert platform_of("https://www.reddit.com/r/saas/comments/abc/launch/") == "reddit"
    assert reddit_json_url(
        "https://www.reddit.com/r/saas/comments/abc/launch/").endswith(".json")
    data = [{
        "data": {"children": [{"kind": "t3", "data": {
            "title": "Acme launched today",
            "author": "alice",
            "score": 42,
            "num_comments": 7,
            "subreddit": "saas",
            "selftext": "We shipped v2",
            "created_utc": 1_700_000_000,
        }}]},
    }]
    payload = from_reddit_json(
        "https://www.reddit.com/r/saas/comments/abc/launch/", data)
    assert payload.assessed is True
    assert payload.upvote_count == 42
    assert payload.comment_count == 7
    assert payload.community == "saas"
    assert payload.view_count is None
    assert any("not impressions" in u["why"] for u in payload.unavailable)
    empty = from_reddit_json("https://www.reddit.com/r/saas/comments/abc/x/", {})
    assert empty.assessed is False


def test_event_bus_records_and_notifies():
    from app.omni.events import ANALYSIS_STARTED, clear, emit, recent, subscribe
    clear()
    seen = []
    subscribe(lambda e: seen.append(e.name))
    emit(ANALYSIS_STARTED, seed="https://acme.example/")
    assert seen == [ANALYSIS_STARTED]
    assert recent()[-1].name == ANALYSIS_STARTED
    clear()


# -------------------------------------------------------------------- oracle
def test_oracle_first_run_is_not_a_forecast():
    from datetime import date

    from app.omni.oracle import forecast
    pred = forecast(current_score=55.0, current_tech=["Stripe"],
                    current_socials=["youtube"], latest_dated="2020-01-01",
                    history=[], today=date(2026, 8, 18))
    assert pred.assessed is False
    assert pred.direction == "unknown"
    assert pred.freshness == "stale"
    assert pred.days_since_dated_content == 2421
    assert any("Traffic" in u for u in pred.unavailable)


def test_oracle_delta_inside_noise_is_stable():
    from app.omni.oracle import HistoryPoint, forecast
    pred = forecast(
        current_score=56.0, current_tech=["Stripe"], current_socials=[],
        latest_dated=None,
        history=[HistoryPoint(overall_score=55.0, tech=["Stripe"])])
    assert pred.assessed is True
    assert pred.direction == "stable"
    assert pred.score_delta == 1.0
    assert pred.confidence < 0.6


def test_oracle_rising_and_tech_diff():
    from app.omni.oracle import HistoryPoint, forecast
    pred = forecast(
        current_score=70.0, current_tech=["Stripe", "HubSpot"], current_socials=[],
        latest_dated=None,
        history=[HistoryPoint(overall_score=55.0, tech=["Stripe"])])
    assert pred.direction == "rising"
    assert pred.tech_added == ["HubSpot"]
    assert pred.score_delta == 15.0


def test_alerts_only_when_watched_and_delta_is_large():
    from app.omni.oracle import detect_changes
    quiet = detect_changes(watched=False, previous_score=50, current_score=80,
                           tech_added=[], tech_removed=[],
                           socials_added=[], socials_removed=[])
    assert quiet == []
    loud = detect_changes(watched=True, previous_score=50, current_score=80,
                          tech_added=["Next.js"], tech_removed=[],
                          socials_added=[], socials_removed=[])
    kinds = {a["kind"] for a in loud}
    assert "score" in kinds and "tech" in kinds
    assert any(a["severity"] == "urgent" for a in loud if a["kind"] == "score")


# ------------------------------------------------------------------ renderer
def test_web_report_renders_offline():
    from app.engine.render.html import render_web

    pages = [extract_page("https://acme.example/", FIXTURE_HTML)]
    scores, overall = _scored()
    payload = WebIntelPayload(
        report_id="t" * 12, generated_at=datetime.now(timezone.utc),
        entity_name="Acme Analytics Pvt Ltd", domain="acme.example",
        seed_url="acme.example", tagline="Acme turns product data into decisions.",
        pages=pages, tech=detect_tech([("https://acme.example/", FIXTURE_HTML)]),
        socials=[SocialPresence(platform="youtube", url="https://youtube.com/@acme",
                                followers=1234)],
        products=[{"name": "Acme Pro", "kind": "product", "price_inr": 4999.0,
                   "rating": None, "rating_count": None, "compare_at_inr": None,
                   "url": None}],
        product_intel={
            "assessed": True, "reason_not_assessed": "", "pricing_model": "paid",
            "offer_count": 1, "price_floor": 4999.0, "price_ceiling": 4999.0,
            "ladder": [{"name": "Acme Pro", "kind": "product", "price_inr": 4999.0,
                        "rating": None, "rating_count": None, "url": None}],
            "positioning": "Public INR ladder spans ₹4,999.",
            "gaps": [], "methodology": "JSON-LD only.",
        },
        competitor_intel={
            "assessed": True, "reason": "", "query_used": "Acme alternatives",
            "competitors": [{"name": "Northwind", "url": "https://northwind.io/",
                             "domain": "northwind.io", "snippet": "BI for teams",
                             "found_via": "Acme alternatives"}],
            "methodology": "search-led official sites.",
        },
        contacts={"emails": ["hello@acme.example"], "phones": []},
        seo={"robots_txt": True, "sitemap_xml": True, "sitemap_url_count": 42,
             "structured_data_types": ["Organization", "Product"]},
        content={"pages_sampled": 1, "total_words": 450, "latest_dated_content": None},
        scores=scores, overall_score=overall,
        opportunities=[{"title": "T", "why": "W", "evidence": "E"}],
        unavailable=[{"item": "Traffic", "why": "first-party analytics"}],
        usage={"pages_sampled": 1, "search_calls": 2, "robots_blocked": 0,
               "http_failed": 0, "search_used": True},
    )
    html = render_web(payload)
    assert "Acme Analytics Pvt Ltd" in html
    assert "Website Intelligence" in html
    assert "1,234" in html                 # live social count rendered
    assert "unavailable" in html           # honesty chips survive
    assert str(overall) in html
    assert "Acme Pro" in html and "Northwind" in html
    assert "Product intelligence" in html
    assert "Narrative radar" in html
    assert "Open public APIs" in html
    assert "First-party feed" in html
    assert "Site signals" in html
    assert "Reviews" in html
    assert "SEO coverage" in html
    assert "Market map" in html
    assert "Critique and synthesis" in html
    assert "Risk radar" in html
    assert "Marketing desk" in html
    assert "2 search call" in html


# ------------------------------------------------------------------ registry
def test_registry_lists_keyless_foundations():
    rows = reg.registry()
    by_name = {p.name: p for p in rows}
    assert by_name["http"].status == reg.STATUS_KEYLESS
    assert by_name["wikipedia"].status == reg.STATUS_KEYLESS
    assert by_name["archive_org"].status == reg.STATUS_KEYLESS
    assert by_name["hackernews"].status == reg.STATUS_KEYLESS
    assert by_name["datamuse"].status == reg.STATUS_KEYLESS
    assert "fetch_page" in by_name["http"].capabilities


def test_registry_health_counters():
    reg.record("t-provider", ok=True, elapsed_ms=100)
    reg.record("t-provider", ok=False, elapsed_ms=300, error="boom")
    h = reg.health("t-provider")
    assert h.calls == 2 and h.error_rate == 0.5 and h.avg_ms == 200
    assert h.last_error == "boom"


# -------------------------------------------------------- entity resolution
def test_name_alone_never_matches():
    from app.omni.resolve import KIND_NAME, Identifier, match_identifiers
    left = Identifier(KIND_NAME, "acme", method="page_extract", confidence=0.45)
    right = Identifier(KIND_NAME, "acme", method="profile", confidence=0.4)
    assert match_identifiers(left, right) is None


def test_hard_identifiers_match():
    from app.omni.resolve import (KIND_DOMAIN, KIND_GSTIN, KIND_HANDLE, KIND_NAME,
                                  Identifier, match_identifiers)
    domain = match_identifiers(
        Identifier(KIND_DOMAIN, "acme.example"),
        Identifier(KIND_DOMAIN, "acme.example"))
    assert domain is not None and domain.rel == "SAME_AS"
    handle = match_identifiers(
        Identifier(KIND_HANDLE, "acme", platform="youtube"),
        Identifier(KIND_HANDLE, "acme", platform="youtube"))
    assert handle is not None and "youtube" in handle.reason
    crossed = match_identifiers(
        Identifier(KIND_HANDLE, "acme", platform="youtube"),
        Identifier(KIND_HANDLE, "acme", platform="instagram"))
    assert crossed is None
    gstin = match_identifiers(
        Identifier(KIND_GSTIN, "27AAPFU0939F1ZV"),
        Identifier(KIND_GSTIN, "27AAPFU0939F1ZV"))
    assert gstin is not None and gstin.rel == "SAME_AS"
    assert match_identifiers(
        Identifier(KIND_GSTIN, "27AAPFU0939F1ZV"),
        Identifier(KIND_NAME, "27AAPFU0939F1ZV")) is None


def test_web_payload_yields_domain_and_social_handle():
    from app.omni.resolve import KIND_DOMAIN, KIND_HANDLE, identifiers_from_web
    pages = [extract_page("https://acme.example/", FIXTURE_HTML)]
    scores, overall = _scored()
    payload = WebIntelPayload(
        report_id="r" * 12, generated_at=datetime.now(timezone.utc),
        entity_name="Acme Analytics Pvt Ltd", domain="acme.example",
        seed_url="https://acme.example/", scores=scores, overall_score=overall,
        pages=pages,
        socials=[SocialPresence(platform="youtube", url="https://youtube.com/@acme",
                                handle="acme")])
    kinds = {(i.kind, i.value, i.platform) for i in identifiers_from_web(payload)}
    assert (KIND_DOMAIN, "acme.example", "") in kinds
    assert (KIND_HANDLE, "acme", "youtube") in kinds
    assert not any(i.kind == "name" and i.value == "acme analytics pvt ltd"
                   for i in identifiers_from_web(payload))
    # name is normalized (legal suffixes stripped) — still not a merge key
    names = [i for i in identifiers_from_web(payload) if i.kind == "name"]
    assert names and names[0].value == "acme analytics"
    payload.identity_intel = {
        "assessed": True,
        "ids": [
            {"kind": "gstin", "value": "27AAPFU0939F1ZV", "url": "https://acme.example/"},
            {"kind": "logo", "value": "https://acme.example/logo.png"},
            {"kind": "gstin", "value": "27AAPFU0939F1Z0"},
        ],
    }
    printed = {(i.kind, i.value) for i in identifiers_from_web(payload)}
    assert ("gstin", "27AAPFU0939F1ZV") in printed
    assert ("gstin", "27AAPFU0939F1Z0") not in printed
    assert not any(i.kind == "logo" for i in identifiers_from_web(payload))


def test_shared_handle_links_website_and_creator():
    from sqlmodel import Session, SQLModel, create_engine, select

    from app.models import Entity, EntityLink
    from app.omni.graph import lookup, upsert_from_creator, upsert_from_web
    from app.omni.resolve import CreatorSurface

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    pages = [extract_page("https://acme.example/", FIXTURE_HTML)]
    scores, overall = _scored()
    payload = WebIntelPayload(
        report_id="w" * 12, generated_at=datetime.now(timezone.utc),
        entity_name="Acme Analytics", domain="acme.example",
        seed_url="https://acme.example/", scores=scores, overall_score=overall,
        pages=pages,
        socials=[SocialPresence(platform="youtube", url="https://youtube.com/@acme",
                                handle="acme", display_name="Acme")])
    with Session(engine) as s:
        site = upsert_from_web(s, payload, org_id=None, report_id="w" * 12)
        site_id = site.id
    with Session(engine) as s:
        creator = upsert_from_creator(
            s, CreatorSurface(name="Acme", handle="acme", platform="youtube",
                              seed_url="https://youtube.com/@acme",
                              website_domains=[("acme.example",
                                                "https://acme.example/")],
                              other_handles=[]),
            org_id=None, report_id="c" * 12)
        creator_id = creator.id
        kinds = {e.kind for e in s.exec(select(Entity)).all()}
        assert kinds == {"website", "creator"}
        rels = {(lnk.from_id, lnk.to_id, lnk.rel)
                for lnk in s.exec(select(EntityLink)).all()}
        assert (site_id, creator_id, "HAS_ACCOUNT") in rels
        assert (creator_id, site_id, "LINKS_TO") in rels
        hit = lookup(s, org_id=None, kind="creator", value="https://youtube.com/@acme",
                     platform="youtube", handle="acme")
        assert hit["verdict"] == "resolved"
        assert hit["matches"][0]["entity_id"] == creator_id


def test_name_overlap_is_insufficient_evidence():
    from sqlmodel import Session, SQLModel, create_engine

    from app.omni.graph import lookup, upsert_from_web
    from app.omni.webintel import WebIntelPayload as W

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    scores, overall = _scored()
    pages = [extract_page("https://acme.example/", FIXTURE_HTML)]
    a = W(report_id="a" * 12, generated_at=datetime.now(timezone.utc),
          entity_name="Acme", domain="acme.example",
          seed_url="https://acme.example/", scores=scores, overall_score=overall,
          pages=pages)
    b = W(report_id="b" * 12, generated_at=datetime.now(timezone.utc),
          entity_name="Acme", domain="other.example",
          seed_url="https://other.example/", scores=scores, overall_score=overall,
          pages=pages)
    with Session(engine) as s:
        upsert_from_web(s, a, org_id=None, report_id="a" * 12)
    with Session(engine) as s:
        upsert_from_web(s, b, org_id=None, report_id="b" * 12)
        found = lookup(s, org_id=None, kind="keyword", value="Acme")
        assert found["verdict"] == "insufficient_evidence"
        assert found["matches"] == []
        assert len(found["candidates"]) >= 1


def test_review_themes_from_jsonld_only():
    from app.omni.reviews import analyse_reviews
    html = """<html><script type="application/ld+json">
    {"@type":"Review","reviewBody":"Too expensive and the interface is confusing",
     "author":{"name":"Sam"},"reviewRating":{"ratingValue":2}}
    </script></html>"""
    intel = analyse_reviews([("https://acme.example/reviews", html)], [])
    assert intel.assessed is True
    assert intel.item_count == 1
    assert "pricing" in intel.themes and "ux" in intel.themes
    empty = analyse_reviews([("https://acme.example/", "<html></html>")], [])
    assert empty.assessed is False


def test_seo_coverage_marks_missing_and_present():
    from types import SimpleNamespace

    from app.omni.seo_map import coverage_map
    pages = [
        SimpleNamespace(url="https://acme.example/pricing", word_count=40, h1=["Plans"], title="Pricing"),
        SimpleNamespace(url="https://acme.example/about", word_count=400, h1=["About"], title="About"),
    ]
    sm = coverage_map(pages, ["https://acme.example/blog/post"])
    by = {s.slot: s.status for s in sm.slots}
    assert by["pricing"] == "thin"
    assert by["about"] == "present"
    assert by["blog"] == "present"   # sitemap only
    assert by["careers"] == "missing"
    assert "Plans" in sm.topics


def test_signal_needs_two_points():
    from app.omni.trends import classify_series
    assert classify_series([50]).assessed is False
    rising = classify_series([50, 60])
    assert rising.classification == "emerging"
    acc = classify_series([50, 60, 72])
    assert acc.classification == "accelerating"
    peak = classify_series([50, 70, 71])
    assert peak.classification == "peak"
    down = classify_series([70, 60])
    assert down.classification == "declining"


def test_document_text_extracts_awards_and_dates():
    from app.omni.documents import analyse_text
    text = "Winner of the Webby Awards on 12 March 2024. Contact press@acme.example."
    intel = analyse_text(text, filename="press.txt", media_type="text/plain")
    assert intel.assessed is True
    assert "Webby Awards" in intel.award_hits
    assert intel.emails == ["press@acme.example"]
    blank = analyse_text("   ", filename="empty.txt", media_type="text/plain")
    assert blank.assessed is False


def test_media_extracts_videoobject_views_only_from_jsonld():
    from app.omni.media import from_public_page, platform_of, views_from_jsonld
    assert platform_of("https://youtu.be/dQw4w9wgWcQ") == "youtube"
    html = """<html><head><title>Ignore me</title>
    <meta property="og:title" content="Launch film">
    <script type="application/ld+json">
    {"@type":"VideoObject","name":"Launch film",
     "interactionStatistic":{"@type":"InteractionCounter",
       "interactionType":"https://schema.org/WatchAction",
       "userInteractionCount":12345}}
    </script></head><body>log in to see more</body></html>"""
    payload = from_public_page("https://www.youtube.com/watch?v=abc", html)
    assert payload.assessed is True
    assert payload.title == "Launch film"
    assert payload.view_count == 12345
    assert views_from_jsonld([]) is None
    empty = from_public_page("https://www.instagram.com/p/AbC/",
                             "<html><body>Sign in</body></html>")
    assert empty.assessed is False


def test_watch_diff_is_empty_when_homepage_stable():
    from app.omni.watch import diff_homepage
    snap = {"title": "Acme", "tech": ["Stripe"], "socials": ["youtube"]}
    assert diff_homepage(snap, snap) == []
    changed = diff_homepage(snap, {"title": "Acme Cloud", "tech": ["Stripe", "HubSpot"],
                                   "socials": ["youtube"]})
    kinds = {d["kind"] for d in changed}
    assert "content" in kinds and "tech" in kinds
    onpage = diff_homepage(
        {"title": "Acme", "onpage": ["embed:youtube"], "ids": []},
        {"title": "Acme", "onpage": ["embed:youtube", "chat:whatsapp"],
         "ids": ["gstin:27AAPFU0939F1ZV"]})
    titles = {d["title"] for d in onpage}
    assert "Homepage on-page surfaces changed" in titles
    assert "Homepage printed identifier changed" in titles


def test_reason_does_not_invent_traffic():
    from app.omni.reason import synthesize_web
    from app.omni.webintel import DimensionScore
    scores = [DimensionScore(key="seo", label="SEO", score=3.0, formula="x")]
    out = synthesize_web(
        scores=scores,
        opportunities=[{"title": "Add meta descriptions"}],
        unavailable=[{"item": "Traffic"}],
        seo_map={"slots": [{"slot": "blog", "status": "missing"}]},
        review_intel={"assessed": False},
        competitor_intel={"assessed": False, "reason": "no key"},
        overall=41.0,
    )
    blob = " ".join(out.findings + out.critiques + out.recommendations)
    assert "41.0" in blob and "blog" in blob
    assert "Add meta descriptions" in out.recommendations
    assert "traffic" in blob.lower() or "Traffic" in blob
    assert "1.2M" not in blob


def test_content_dna_reads_hooks_and_ctas():
    from types import SimpleNamespace

    from app.omni.content_dna import from_pages
    pages = [SimpleNamespace(
        h1=["Product intelligence for teams"], cta_hits=["book a demo", "free trial"],
        forms=1, lang="en", dates_seen=["2026-01-01"])]
    dna = from_pages(pages)
    assert dna.assessed is True
    assert "Product intelligence for teams" in dna.hooks
    assert "book a demo" in dna.ctas
    assert from_pages([]).assessed is False


def test_risk_elevated_needs_two_crisis_items():
    from app.omni.risk import from_news
    quiet = from_news({"assessed": True, "items": [
        {"narrative": "growth", "title": "Raises round"}]})
    assert quiet.level == "none"
    watch = from_news({"assessed": True, "items": [
        {"narrative": "crisis", "title": "Sued"}]})
    assert watch.level == "watch"
    hot = from_news({"assessed": True, "items": [
        {"narrative": "crisis", "title": "Sued"},
        {"narrative": "crisis", "title": "Breach"}]})
    assert hot.level == "elevated" and hot.crisis_n == 2
    assert from_news({"assessed": False, "reason": "no key"}).assessed is False


def test_usable_orders_active_before_keyless():
    rows = reg.usable()
    statuses = [p.status for p in rows]
    if reg.STATUS_ACTIVE in statuses:
        assert statuses.index(reg.STATUS_ACTIVE) < statuses.index(reg.STATUS_KEYLESS)
    assert all(p.status != reg.STATUS_OFF for p in rows)


# ------------------------------------------------------ timeline / award dates
def test_award_dates_classifies_deadline_not_ceremony():
    from app.omni.award_dates import extract_dates
    html = """<html><body>
    <p>The entry deadline is June 15, 2026 for all categories.</p>
    <p>Awards night ceremony August 20, 2026 in Cannes.</p>
    </body></html>"""
    intel = extract_dates(html, "https://awards.example/", name="Demo Lions")
    assert intel.assessed is True
    kinds = {d.kind: d.raw for d in intel.dates}
    assert "deadline" in kinds and "ceremony" in kinds
    assert all(d.source_url == "https://awards.example/" for d in intel.dates)


def test_award_dates_empty_is_unavailable():
    from app.omni.award_dates import extract_dates
    intel = extract_dates(
        "<html><body><p>Welcome to the awards home.</p></body></html>",
        "https://awards.example/", name="Demo")
    assert intel.assessed is False
    assert intel.dates == []
    assert "no dates" in intel.reason.lower()


def test_timeline_orders_newest_and_reuses_stored_news():
    import json
    from datetime import datetime

    from sqlmodel import Session, SQLModel, create_engine

    from app.models import Alert, Entity, EntitySnapshot, Report
    from app.omni.timeline import brief_from_report, from_stores

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    payload = {
        "reasoning": {"findings": ["Website intelligence score is 62/100 from six public dimensions."]},
        "news_intel": {"items": [{"title": "Acme raises", "narrative": "growth",
                                  "url": "https://news.example/acme"}]},
    }
    with Session(engine) as s:
        s.add(Entity(id="ent1", name="Acme", domain="acme.example", last_report_id="rep1"))
        s.add(Report(
            id="rep1", job_id="job1", share_slug="slug1", subject_name="Acme",
            subject_handle="", seed_url="https://acme.example/", html_path="/tmp/x.html",
            payload_json=json.dumps(payload), created_at=datetime(2026, 3, 1)))
        s.add(EntitySnapshot(
            id="snap1", entity_id="ent1", report_id="rep1", overall_score=62,
            created_at=datetime(2026, 1, 10)))
        s.add(Alert(
            id="al1", entity_id="ent1", kind="score", severity="watch",
            title="Score moved", detail="62 → 71", created_at=datetime(2026, 2, 1)))
        s.commit()
        report = s.get(Report, "rep1")
        events = from_stores(s, "ent1", report=report)
        kinds = [e.kind for e in events]
        assert kinds[0] == "news"
        assert "alert" in kinds and "snapshot" in kinds
        assert events[0].title == "Acme raises"
        assert brief_from_report(report) == [
            "Website intelligence score is 62/100 from six public dimensions."]
        assert brief_from_report(None) == []


# ---------------------------------------------------------- compare / usage
def test_compare_shared_tech_and_honest_gap():
    from app.omni.compare import compare_payloads
    left = {
        "entity_name": "Acme", "domain": "acme.example", "overall_score": 62.0,
        "scores": [{"key": "seo", "score": 6}, {"key": "trust", "score": 4}],
        "tech": [{"name": "Next.js"}, {"name": "Stripe"}],
        "socials": [{"platform": "youtube", "error": ""}],
        "competitor_intel": {"competitors": [{"domain": "northwind.io", "name": "Northwind"}]},
        "seo_map": {"slots": [{"slot": "pricing", "status": "missing"}]},
        "risk_intel": {"level": "none"},
    }
    right = {
        "entity_name": "Contoso", "domain": "contoso.example", "overall_score": 71.0,
        "scores": [{"key": "seo", "score": 8}],
        "tech": [{"name": "Next.js"}, {"name": "HubSpot"}],
        "socials": [{"platform": "youtube", "error": ""}, {"platform": "x", "error": ""}],
        "competitor_intel": {"competitors": [{"domain": "northwind.io", "name": "Northwind"}]},
        "seo_map": {"slots": [{"slot": "pricing", "status": "present"}]},
        "risk_intel": {"level": "watch"},
    }
    intel = compare_payloads(left, right)
    assert intel.assessed is True
    assert intel.score_delta == 9.0
    assert "Contoso" in intel.verdict
    assert "market share" in intel.verdict.lower()
    assert intel.shared_tech == ["Next.js"]
    assert "Stripe" in intel.left_only_tech and "HubSpot" in intel.right_only_tech
    assert intel.shared_socials == ["youtube"]
    assert intel.shared_rivals == ["northwind.io"]
    trust = next(r for r in intel.rows if r.field == "trust")
    assert trust.right == "—" and trust.note == "left_only"


def test_compare_same_domain_is_not_assessed():
    from app.omni.compare import compare_payloads
    payload = {"entity_name": "Acme", "domain": "acme.example", "overall_score": 50}
    intel = compare_payloads(payload, {"entity_name": "Acme Inc", "domain": "acme.example",
                                      "overall_score": 60})
    assert intel.assessed is False
    assert "same domain" in intel.reason.lower()


def test_compare_empty_is_insufficient():
    from app.omni.compare import compare_payloads
    intel = compare_payloads({}, {"entity_name": "Acme", "domain": "acme.example"})
    assert intel.assessed is False
    assert "two stored" in intel.reason.lower()


def test_usage_search_counter_is_per_reset():
    from app.omni.usage import add_search, reset_search, search_calls
    reset_search()
    assert search_calls() == 0
    add_search()
    add_search()
    assert search_calls() == 2
    reset_search()
    assert search_calls() == 0


# ---------------------------------------------------------- digest / bluesky
def test_digest_ignores_old_alerts_and_small_score_moves():
    from datetime import datetime, timedelta

    from sqlmodel import Session, SQLModel, create_engine

    from app.models import Alert, Entity, EntitySnapshot
    from app.omni.digest import build

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    now = datetime.utcnow()
    with Session(engine) as s:
        s.add(Entity(id="e1", name="Acme", domain="acme.example", watched=True))
        s.add(Entity(id="e2", name="Quiet Co", domain="quiet.example", watched=True))
        s.add(Entity(id="e3", name="Northwind", domain="northwind.example", watched=False))
        s.add(Alert(id="old", entity_id="e1", kind="score", title="Ancient",
                    created_at=now - timedelta(days=20)))
        s.add(Alert(id="new", entity_id="e1", kind="tech", title="Pixel added",
                    detail="Meta Pixel", created_at=now - timedelta(hours=12)))
        s.add(EntitySnapshot(id="s1", entity_id="e1", overall_score=50,
                             created_at=now - timedelta(days=3)))
        s.add(EntitySnapshot(id="s2", entity_id="e1", overall_score=52,
                             created_at=now - timedelta(hours=2)))
        s.add(EntitySnapshot(id="n1", entity_id="e3", overall_score=40,
                             created_at=now - timedelta(days=4)))
        s.add(EntitySnapshot(id="n2", entity_id="e3", overall_score=55,
                             created_at=now - timedelta(hours=1)))
        s.commit()
        intel = build(s, None, days=7)
        titles = [i.title for i in intel.items]
        assert intel.assessed is True
        assert "Pixel added" in titles
        assert "Ancient" not in titles
        assert any(i.kind == "score" and i.entity_name == "Northwind" for i in intel.items)
        assert not any(i.kind == "score" and i.entity_name == "Acme" for i in intel.items)
        assert "Quiet Co" in intel.silent_watched
        assert "Acme" not in intel.silent_watched


def test_digest_empty_window_is_insufficient():
    from sqlmodel import Session, SQLModel, create_engine

    from app.omni.digest import build

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        intel = build(s, None, days=7)
        assert intel.assessed is False
        assert "no stored" in intel.reason.lower()


def test_bluesky_thread_likes_are_not_reach():
    from app.omni.media import bluesky_at_uri, from_bluesky_thread, platform_of
    url = "https://bsky.app/profile/alice.bsky.social/post/3kabc"
    assert platform_of(url) == "bluesky"
    assert bluesky_at_uri(url) == "at://alice.bsky.social/app.bsky.feed.post/3kabc"
    data = {"thread": {"post": {
        "likeCount": 12, "replyCount": 3,
        "author": {"handle": "alice.bsky.social"},
        "record": {"text": "We shipped v2", "createdAt": "2026-06-01T12:00:00Z"},
    }}}
    payload = from_bluesky_thread(url, data)
    assert payload.assessed is True
    assert payload.upvote_count == 12
    assert payload.comment_count == 3
    assert payload.view_count is None
    assert any("not impressions" in u["why"] for u in payload.unavailable)
    empty = from_bluesky_thread(url, {})
    assert empty.assessed is False


# ----------------------------------------------------- export / hubs / tiktok
def test_pack_report_is_stored_payload_only():
    from datetime import datetime

    from app.models import Report
    from app.omni.export import pack_report

    assert pack_report(None) is None
    blank = Report(
        id="r1", job_id="j1", share_slug="acme-r1", subject_name="Acme",
        subject_handle="", seed_url="https://acme.example/", html_path="/tmp/x.html")
    assert pack_report(blank) is None
    blank.payload_json = '{"entity_name":"Acme","overall_score":62}'
    blank.created_at = datetime(2026, 6, 1, 12, 0, 0)
    pack = pack_report(blank)
    assert pack["kind"] == "single"
    assert pack["slug"] == "acme-r1"
    assert pack["payload"]["overall_score"] == 62
    assert "Missing fields stay missing" in pack["note"]


def test_opportunity_and_social_rows_skip_empty():
    from app.models import Report
    from app.omni.hubs import opportunity_rows, social_rows

    report = Report(
        id="r1", job_id="j1", share_slug="acme-r1", subject_name="Acme",
        subject_handle="", seed_url="https://acme.example/", html_path="/tmp/x.html")
    data = {
        "entity_name": "Acme",
        "opportunities": [
            {"title": "Publish a sitemap.xml", "why": "None found", "evidence": "technical"},
            {"title": "", "why": "ignore"},
        ],
        "socials": [
            {"platform": "youtube", "handle": "acme", "followers": 12, "error": ""},
            {"platform": "x", "handle": "", "error": "collection failed"},
        ],
    }
    opps = opportunity_rows([(report, data)])
    assert len(opps) == 1 and opps[0]["title"].startswith("Publish")
    socials = social_rows([(report, data)])
    assert [s["platform"] for s in socials] == ["youtube", "x"]
    assert socials[1]["status"] == "collection failed"


def test_tiktok_oembed_does_not_invent_views():
    from app.omni.media import from_public_page, platform_of, tiktok_oembed_url
    url = "https://www.tiktok.com/@acme/video/123"
    assert platform_of(url) == "tiktok"
    assert "tiktok.com/oembed" in tiktok_oembed_url(url)
    html = "<html><head><title>Clip</title></head><body>1.2M views</body></html>"
    payload = from_public_page(url, html, oembed={
        "title": "Launch clip", "author_name": "acme",
        "thumbnail_url": "https://example.com/t.jpg",
    })
    assert payload.assessed is True
    assert payload.title == "Launch clip"
    assert payload.view_count is None
    assert any("View" in u["item"] for u in payload.unavailable)


# ------------------------------------------------ coverage / contacts / csv
def test_coverage_distinguishes_assessed_empty_unavailable():
    from app.omni.coverage import from_payload
    data = {
        "entity_name": "Acme", "domain": "acme.example", "overall_score": 62,
        "product_intel": {"assessed": True, "ladder": [{"name": "Pro"}]},
        "competitor_intel": {"assessed": True, "competitors": []},
        "news_intel": {"assessed": False, "reason": "no key", "items": []},
        "review_intel": {"assessed": True, "themes": {"fast": 2}},
        "socials": [{"platform": "youtube", "error": ""}],
        "seo_map": {"slots": [{"slot": "pricing", "status": "missing"}]},
    }
    cov = from_payload(data)
    assert cov.slots["products"] == "assessed"
    assert cov.slots["competitors"] == "empty"
    assert cov.slots["news"] == "unavailable"
    assert cov.slots["feeds"] == "missing"
    assert cov.slots["reviews"] == "assessed"
    assert cov.slots["socials"] == "assessed"
    assert cov.slots["seo"] == "assessed"
    assert cov.slots["market"] == "missing"
    assert cov.assessed_n >= 4
    assert cov.unavailable_n >= 1


def test_contact_rows_only_published_values():
    from app.models import Report
    from app.omni.hubs import contact_rows

    report = Report(
        id="r1", job_id="j1", share_slug="acme-r1", subject_name="Acme",
        subject_handle="", seed_url="https://acme.example/", html_path="/tmp/x.html")
    rows = contact_rows([(report, {
        "entity_name": "Acme",
        "contacts": {"emails": ["hello@acme.example", ""], "phones": ["+91 22 0000 0000"]},
    })])
    assert [r["value"] for r in rows] == ["hello@acme.example", "+91 22 0000 0000"]
    assert {r["kind"] for r in rows} == {"email", "phone"}


def test_rows_to_csv_quotes_commas():
    from app.omni.export import rows_to_csv
    text = rows_to_csv(["name", "why"], [["Acme", "a, b"]])
    assert text.splitlines()[0] == "name,why"
    assert '"a, b"' in text


# ------------------------------------------ frontier / graph / mentions
def test_crawl_frontier_is_sitemap_first():
    from app.omni.webintel import crawl_frontier
    ordered = crawl_frontier(
        "acme.example", "https://acme.example/",
        ["https://acme.example/pricing", "https://other.com/pricing"],
        ["https://acme.example/legal/terms", "https://acme.example/about"],
        budget=5,
    )
    assert ordered[0] == "https://acme.example/about"
    assert ordered[1] == "https://acme.example/pricing"
    assert ordered[2] == "https://acme.example/legal/terms"
    assert all("other.com" not in u for u in ordered)
    assert not any(u.rstrip("/") == "https://acme.example" for u in ordered)
    empty = crawl_frontier("acme.example", "https://acme.example/", [], [], budget=4)
    assert empty == []


def test_mentions_require_stored_domain_not_name():
    from app.models import Entity, Report
    from app.omni.mentions import from_payloads

    acme = Entity(id="e1", name="Acme", domain="acme.example")
    north = Entity(id="e2", name="Northwind", domain="northwind.io")
    quiet = Entity(id="e3", name="Quiet Co", domain="quiet.example")
    report = Report(
        id="r1", job_id="j1", share_slug="acme-r1", subject_name="Acme",
        subject_handle="", seed_url="https://acme.example/", html_path="/tmp/x.html")
    data = {
        "entity_name": "Acme", "domain": "acme.example",
        "competitor_intel": {"competitors": [
            {"domain": "northwind.io", "name": "Northwind", "snippet": "BI"},
            {"domain": "g2.com", "name": "Quiet Co"},
        ]},
        "news_intel": {"items": [
            {"title": "Quiet Co raises", "snippet": "Quiet Co funding", "url": "https://news.example/x"},
        ]},
    }
    rows = from_payloads([(report, data)], [acme, north, quiet])
    domains = {(r.mentioned_domain, r.via) for r in rows}
    assert ("northwind.io", "competitor") in domains
    assert not any(r.mentioned_domain == "quiet.example" for r in rows)


def test_mentions_match_printed_gstin_not_a_name():
    from app.models import Entity, Report
    from app.omni.mentions import from_payloads

    acme = Entity(id="e1", name="Acme", domain="acme.example")
    north = Entity(id="e2", name="Northwind", domain="northwind.io")
    acme_report = Report(
        id="r1", job_id="j1", share_slug="acme-r1", subject_name="Acme",
        subject_handle="", seed_url="https://acme.example/", html_path="/tmp/x.html")
    north_report = Report(
        id="r2", job_id="j2", share_slug="north-r2", subject_name="Northwind",
        subject_handle="", seed_url="https://northwind.io/", html_path="/tmp/y.html")
    acme_data = {
        "entity_name": "Acme", "domain": "acme.example",
        "news_intel": {"items": [
            {"title": "Filing cites 27AAPFU0939F1ZV", "snippet": "", "url": "https://news.example/x"},
            {"title": "Northwind expands", "snippet": "the brand Northwind", "url": "https://news.example/y"},
        ]},
    }
    north_data = {
        "entity_name": "Northwind", "domain": "northwind.io",
        "identity_intel": {"assessed": True, "ids": [
            {"kind": "gstin", "value": "27AAPFU0939F1ZV"},
        ]},
    }
    rows = from_payloads(
        [(acme_report, acme_data), (north_report, north_data)],
        [acme, north])
    assert any(r.mentioned_domain == "northwind.io" and r.via == "news" for r in rows)
    assert not any("expands" in (r.evidence or "") for r in rows)


def test_unavailable_rows_skip_malformed():
    from app.models import Report
    from app.omni.hubs import unavailable_rows

    report = Report(
        id="r1", job_id="j1", share_slug="acme-r1", subject_name="Acme",
        subject_handle="", seed_url="https://acme.example/", html_path="/tmp/x.html")
    rows = unavailable_rows([(report, {
        "entity_name": "Acme",
        "unavailable": [
            {"item": "Traffic", "why": "First-party analytics"},
            {"why": "missing item key"},
            "not-a-dict",
        ],
    })])
    assert len(rows) == 1
    assert rows[0]["item"] == "Traffic"
    assert rows[0]["why"] == "First-party analytics"
    assert rows[0]["href"] == "/r/acme-r1"


def test_sitemap_index_expands_same_host_only():
    from app.omni.webintel import child_sitemaps, is_sitemap_index, sitemap_locs

    index = (
        '<?xml version="1.0"?>'
        "<sitemapindex>"
        "<sitemap><loc>https://acme.example/sitemap-pages.xml</loc></sitemap>"
        "<sitemap><loc>https://other.com/sitemap.xml</loc></sitemap>"
        "<sitemap><loc>https://acme.example/sitemap-blog.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    assert is_sitemap_index(index)
    kids = child_sitemaps(index, "acme.example")
    assert kids == [
        "https://acme.example/sitemap-pages.xml",
        "https://acme.example/sitemap-blog.xml",
    ]
    urlset = (
        '<?xml version="1.0"?>'
        "<urlset><url><loc>https://acme.example/about</loc></url></urlset>"
    )
    assert not is_sitemap_index(urlset)
    assert child_sitemaps(urlset, "acme.example") == []
    assert sitemap_locs(urlset) == ["https://acme.example/about"]
    assert sitemap_locs("") == []


def test_graph_map_uses_stored_links_only():
    from sqlmodel import Session, SQLModel, create_engine

    from app.models import Entity, EntityLink
    from app.omni.graphmap import build

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Entity(id="w1", name="Acme", kind="website", domain="acme.example"))
        s.add(Entity(id="c1", name="@acme", kind="creator", domain=""))
        s.add(EntityLink(id="l1", from_id="w1", to_id="c1", rel="HAS_ACCOUNT",
                         evidence="sameAs youtube", method="hard_id", confidence=0.8))
        s.commit()
        g = build(s, None)
        assert g.assessed is True
        assert len(g.nodes) == 2 and len(g.edges) == 1
        assert g.edges[0].rel == "HAS_ACCOUNT"
        assert g.isolated_n == 0
    with Session(engine) as s:
        empty = create_engine("sqlite://")
        SQLModel.metadata.create_all(empty)
        with Session(empty) as s2:
            assert build(s2, None).assessed is False


# ------------------------------------------------ first-party feeds
def test_discover_feed_urls_same_host_only():
    from app.omni.feeds import discover_feed_urls
    html = (
        '<html><head>'
        '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
        '<link rel="alternate" type="application/rss+xml" '
        'href="https://other.com/feed.xml">'
        '<link rel="stylesheet" href="/style.css">'
        '</head><body>'
        '<a href="/blog">Blog</a>'
        '<a href="https://acme.example/atom.xml">Atom</a>'
        '</body></html>'
    )
    urls = discover_feed_urls("https://acme.example/", html)
    assert "https://acme.example/feed.xml" in urls
    assert "https://acme.example/atom.xml" in urls
    assert all("other.com" not in u for u in urls)
    assert discover_feed_urls("https://acme.example/", "<html><p>hi</p></html>") == []


def test_parse_feed_dates_come_from_fields_not_titles():
    from app.omni.feeds import normalize_date, parse_feed
    rss = (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<item><title>Best of 2024 recap</title>"
        "<link>https://acme.example/blog/2024-recap</link></item>"
        "<item><title>Launch</title>"
        "<link>https://acme.example/blog/launch</link>"
        "<pubDate>Wed, 19 Aug 2026 10:00:00 +0000</pubDate></item>"
        "</channel></rss>"
    )
    items = {i.title: i for i in parse_feed(rss, "https://acme.example/feed.xml")}
    assert items["Best of 2024 recap"].published == ""
    assert items["Launch"].published == "2026-08-19"
    atom = (
        '<?xml version="1.0"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        "<entry><title>Hello</title>"
        '<link href="https://acme.example/p/hello" rel="alternate"/>'
        "<published>2026-07-04T09:00:00Z</published></entry></feed>"
    )
    parsed = parse_feed(atom, "https://acme.example/atom.xml")
    assert parsed[0].title == "Hello"
    assert parsed[0].url == "https://acme.example/p/hello"
    assert parsed[0].published == "2026-07-04"
    assert normalize_date("2026-08-01T12:00:00Z") == "2026-08-01"
    assert normalize_date("not a date") == ""
    assert parse_feed("<html>not a feed <item>", "https://acme.example/x") == []


def test_feed_rows_require_assessed_items():
    from app.models import Report
    from app.omni.hubs import feed_rows

    report = Report(
        id="r1", job_id="j1", share_slug="acme-r1", subject_name="Acme",
        subject_handle="", seed_url="https://acme.example/", html_path="/tmp/x.html")
    empty = feed_rows([(report, {
        "entity_name": "Acme",
        "feed_intel": {"assessed": False, "items": [{"title": "Nope"}]},
    })])
    assert empty == []
    rows = feed_rows([(report, {
        "entity_name": "Acme",
        "feed_intel": {"assessed": True, "items": [
            {"title": "Launch", "published": "2026-08-19",
             "url": "https://acme.example/p"},
        ]},
    })])
    assert rows[0]["title"] == "Launch"
    assert rows[0]["published"] == "2026-08-19"


def test_parse_robots_records_directives_not_secrets():
    from app.omni.site import from_headers, parse_robots
    empty = parse_robots("")
    assert empty.assessed is False
    intel = parse_robots(
        "User-agent: *\nDisallow: /admin\nAllow: /public\n"
        "Sitemap: https://acme.example/sitemap.xml\nCrawl-delay: 10\n")
    assert intel.assessed is True
    assert "/admin" in intel.disallow
    assert "/public" in intel.allow
    assert intel.sitemaps == ["https://acme.example/sitemap.xml"]
    assert intel.crawl_delay == "10"
    headers = from_headers({
        "Strict-Transport-Security": "max-age=31536000",
        "content-type": "text/html",
    })
    assert headers.assessed is True
    assert "strict-transport-security" in headers.present
    assert "content-security-policy" in headers.missing


def test_schema_inventory_reads_jsonld_only():
    from app.omni.schema_intel import analyse_schema
    intel = analyse_schema([("https://acme.example/", FIXTURE_HTML)])
    assert intel.assessed is True
    assert intel.types.get("Organization") == 1
    assert intel.types.get("Product") == 1
    assert any(i.type == "Organization" for i in intel.items)
    blank = analyse_schema([("https://acme.example/", "<html><p>no schema</p></html>")])
    assert blank.assessed is False


def test_schema_extracts_faq_jobs_events_nap_hreflang():
    from app.omni.schema_intel import analyse_schema
    html = """<html><head>
    <link rel="alternate" hreflang="hi-IN" href="https://acme.example/hi/">
    <link rel="alternate" hreflang="en" href="https://other.com/en/">
    <script type="application/ld+json">
    {"@graph":[
      {"@type":"Organization","name":"Acme","telephone":"+91 22 0000 0000",
       "address":{"streetAddress":"1 MG Road","addressLocality":"Bengaluru"},
       "foundingDate":"2018-04-01"},
      {"@type":"FAQPage","mainEntity":[
        {"@type":"Question","name":"What is Acme?",
         "acceptedAnswer":{"@type":"Answer","text":"A product intelligence tool."}}]},
      {"@type":"JobPosting","title":"Analyst","datePosted":"2026-08-01",
       "jobLocation":{"address":{"addressLocality":"Bengaluru"}}},
      {"@type":"Event","name":"Launch meetup","startDate":"2026-09-01",
       "location":{"name":"Bengaluru"}}
    ]}
    </script></head><body></body></html>"""
    intel = analyse_schema([("https://acme.example/", html)])
    assert intel.assessed is True
    assert intel.faqs[0].question == "What is Acme?"
    assert "product intelligence" in intel.faqs[0].answer
    assert intel.jobs[0].title == "Analyst"
    assert intel.jobs[0].location == "Bengaluru"
    assert intel.jobs[0].date_posted.startswith("2026-08-01")
    assert intel.events[0].name == "Launch meetup"
    assert intel.nap is not None
    assert intel.nap.telephone.startswith("+91")
    assert "Bengaluru" in intel.nap.address
    assert intel.nap.founding_date == "2018-04-01"
    langs = {h.lang: h.url for h in intel.hreflang}
    assert langs.get("hi-in") == "https://acme.example/hi/"
    assert "en" not in langs


def test_structured_rows_skip_empty_schema():
    from app.models import Report
    from app.omni.hubs import structured_rows
    report = Report(
        id="r1", job_id="j1", share_slug="acme-r1", subject_name="Acme",
        subject_handle="", seed_url="https://acme.example/", html_path="/tmp/x.html")
    assert structured_rows([(report, {"schema_intel": {"assessed": True}})]) == []
    rows = structured_rows([(report, {"entity_name": "Acme", "schema_intel": {
        "faqs": [{"question": "What?", "answer": "This."}],
        "jobs": [{"title": "Analyst", "location": "Bengaluru"}],
    }})])
    kinds = {r["kind"] for r in rows}
    assert kinds == {"faq", "job"}


def test_sitemap_lastmod_orders_other_urls():
    from app.omni.webintel import crawl_frontier, sitemap_entries
    xml = (
        "<urlset>"
        "<url><loc>https://acme.example/legal/old</loc>"
        "<lastmod>2020-01-01</lastmod></url>"
        "<url><loc>https://acme.example/legal/new</loc>"
        "<lastmod>2026-08-01</lastmod></url>"
        "</urlset>"
    )
    entries = sitemap_entries(xml)
    assert entries[0][1] == "2020-01-01"
    lastmods = {u: d for u, d in entries}
    ordered = crawl_frontier(
        "acme.example", "https://acme.example/",
        [],
        ["https://acme.example/legal/old", "https://acme.example/legal/new"],
        budget=4, lastmods=lastmods)
    assert ordered[0] == "https://acme.example/legal/new"


def test_canonical_conflict_is_host_mismatch():
    from types import SimpleNamespace

    from app.omni.seo_map import coverage_map
    pages = [SimpleNamespace(
        url="https://acme.example/", word_count=200, h1=["Home"], title="Acme",
        canonical="https://other.com/")]
    sm = coverage_map(pages, [])
    assert sm.canonical_conflicts
    assert "other.com" in sm.canonical_conflicts[0]


def test_schema_breadcrumbs_articles_hours_from_printed_fields():
    from app.omni.schema_intel import analyse_schema
    html = """<html><head>
    <script type="application/ld+json">
    {"@graph":[
      {"@type":"LocalBusiness","name":"Acme","openingHours":"Mo-Fr 09:00-18:00",
       "geo":{"latitude":12.97,"longitude":77.59}},
      {"@type":"BreadcrumbList","itemListElement":[
        {"@type":"ListItem","position":2,"name":"Pricing"},
        {"@type":"ListItem","position":1,"name":"Home"}
      ]},
      {"@type":"BlogPosting","headline":"Best of 2024 recap",
       "datePublished":"2026-08-01"},
      {"@type":"Article","name":"Launch 2025"}
    ]}
    </script></head><body></body></html>"""
    intel = analyse_schema([("https://acme.example/pricing", html)])
    assert intel.breadcrumbs[0].path == "Home › Pricing"
    recap = next(a for a in intel.articles if a.title == "Best of 2024 recap")
    assert recap.published == "2026-08-01"
    launch = next(a for a in intel.articles if a.title == "Launch 2025")
    assert launch.published == ""
    assert recap.modified == ""
    assert launch.modified == ""
    assert intel.nap is not None
    assert "09:00" in intel.nap.hours
    assert intel.nap.geo == "12.97,77.59"
    assert intel.item_lists == []
    assert intel.hours == []


def test_visible_rupee_is_not_a_sku_and_needs_commerce_words():
    from app.omni.products import analyse_products, visible_rupee_prices
    html = (
        "<html><body>"
        "<p>Course fee ₹4,999 this week</p>"
        "<p>We found ₹500 notes in the drawer</p>"
        "</body></html>"
    )
    visible = visible_rupee_prices([("https://acme.example/about", html)])
    assert [v["amount"] for v in visible] == [4999.0]
    page = extract_page("https://acme.example/about", html)
    intel = analyse_products([], [page], raw_html=[("https://acme.example/about", html)])
    assert intel.assessed is True
    assert intel.ladder == []
    assert intel.visible_prices[0]["amount"] == 4999.0
    bare = extract_page("https://bare.example/", "<html><body><p>₹500 notes</p></body></html>")
    empty = analyse_products([], [bare], raw_html=[("https://bare.example/", "<html><body><p>₹500 notes</p></body></html>")])
    assert empty.assessed is False
    assert empty.ladder == []


def test_declared_surfaces_keep_offhost_github_not_invented_status():
    from app.omni.surfaces import classify_surface, from_links
    assert classify_surface("https://github.com/acme/app") == "github"
    assert classify_surface("https://github.com/pricing") is None
    assert classify_surface("https://apps.apple.com/app/id1") == "appstore"
    assert classify_surface("https://play.google.com/store/apps/details?id=x") == "playstore"
    assert classify_surface("https://acme.statuspage.io") == "status"
    assert classify_surface("https://acme.example/status") == "status"
    assert classify_surface("https://acme.example/about") is None
    intel = from_links([
        "https://github.com/acme/app",
        "https://apps.apple.com/app/id1",
        "https://acme.example/blog",
    ])
    kinds = {link.kind for link in intel.links}
    assert kinds == {"github", "appstore"}
    assert any(link.url == "https://github.com/acme/app" for link in intel.links)
    blank = from_links(["https://acme.example/about"])
    assert blank.assessed is True
    assert blank.links == []


def test_legal_dates_need_update_wording_not_footer_year():
    from app.omni.legal import analyse_legal, policy_kind
    assert policy_kind("https://acme.example/privacy") == "privacy"
    assert policy_kind("https://acme.example/testimonials") is None
    assert policy_kind("https://acme.example/") is None
    html = """<html><head><title>Privacy</title></head><body>
    <p>Last updated: August 1, 2026</p>
    <p>© 2019 Acme. All rights reserved.</p>
    </body></html>"""
    intel = analyse_legal([("https://acme.example/privacy", html)])
    assert intel.assessed is True
    assert intel.policies[0].updated == "2026-08-01"
    assert intel.latest_updated == "2026-08-01"
    home = analyse_legal([("https://acme.example/", "<html><body><p>Last updated: August 1, 2026</p></body></html>")])
    assert home.assessed is False


def test_gstin_needs_checksum_cin_is_pattern_only():
    from app.omni.identity import analyse_identity, gstin_valid
    assert gstin_valid("27AAPFU0939F1ZV") is True
    assert gstin_valid("27AAPFU0939F1Z0") is False
    html = """<html><body>
    <p>GSTIN 27AAPFU0939F1ZV</p>
    <p>Reject 27AAPFU0939F1Z0</p>
    <p>CIN U72200KA2018PTC123456</p>
    <script type="application/ld+json">
    {"@type":"Organization","name":"Acme","logo":"https://acme.example/logo.png",
     "taxID":"27AAPFU0939F1ZV"}
    </script>
    </body></html>"""
    intel = analyse_identity([("https://acme.example/", html)])
    kinds = {row.kind: row.value for row in intel.ids}
    assert kinds["gstin"] == "27AAPFU0939F1ZV"
    assert kinds["cin"] == "U72200KA2018PTC123456"
    assert kinds["logo"] == "https://acme.example/logo.png"
    assert "27AAPFU0939F1Z0" not in {row.value for row in intel.ids}
    blank = analyse_identity([("https://acme.example/", "<html><p>hello</p></html>")])
    assert blank.assessed is False


def test_schema_people_video_howto_search_from_printed_fields():
    from app.omni.schema_intel import analyse_schema
    html = """<html><head><script type="application/ld+json">
    {"@graph":[
      {"@type":"Person","name":"Ada West","jobTitle":"Analyst"},
      {"@type":"VideoObject","name":"Launch 2025 recap",
       "uploadDate":"2026-08-01","embedUrl":"https://www.youtube.com/embed/x"},
      {"@type":"HowTo","name":"Install Acme","step":[
        {"@type":"HowToStep","name":"Download"},
        {"@type":"HowToStep","name":"Run"},
        {"@type":"HowToStep","name":"Sign in"}]},
      {"@type":"WebSite","name":"Acme",
       "potentialAction":{"@type":"SearchAction",
         "target":{"@type":"EntryPoint",
           "urlTemplate":"https://acme.example/search?q={search_term_string}"}}}
    ]}
    </script></head><body></body></html>"""
    intel = analyse_schema([("https://acme.example/", html)])
    assert intel.people[0].name == "Ada West"
    assert intel.people[0].job_title == "Analyst"
    assert intel.videos[0].title == "Launch 2025 recap"
    assert intel.videos[0].uploaded == "2026-08-01"
    assert intel.howtos[0].name == "Install Acme"
    assert intel.howtos[0].steps == 3
    assert intel.howtos[0].tools == []
    assert intel.howtos[0].supplies == []
    assert "{search_term_string}" in intel.search_actions[0].target


def test_serving_and_offer_terms_are_printed_fields():
    from app.omni.products import analyse_products, offer_terms
    from app.omni.schema_intel import analyse_schema
    html = """<html><head><script type="application/ld+json">
    {"@graph":[
      {"@type":"Organization","name":"Acme","areaServed":"India",
       "paymentAccepted":"UPI","priceRange":"₹₹","availableLanguage":"en",
       "numberOfEmployees":40,"alternateName":"Acme Analytics"},
      {"@type":"Product","name":"Acme Pro",
       "offers":{"price":"4999","priceCurrency":"INR",
         "availability":"https://schema.org/InStock",
         "priceValidUntil":"2026-12-31"}}
    ]}
    </script></head><body></body></html>"""
    schema = analyse_schema([("https://acme.example/", html)])
    assert schema.serving is not None
    assert schema.serving.area == "India"
    assert "UPI" in schema.serving.payments
    assert schema.serving.employees == "40"
    assert "Acme Analytics" in schema.serving.also_known
    terms = offer_terms([("https://acme.example/", html)])
    assert terms["acme pro"]["availability"] == "InStock"
    assert terms["acme pro"]["valid_until"] == "2026-12-31"
    page = extract_page("https://acme.example/pricing", html)
    intel = analyse_products(
        [{"name": "Acme Pro", "kind": "product", "price_inr": 4999.0}],
        [page], raw_html=[("https://acme.example/", html)])
    assert intel.ladder[0].availability == "InStock"
    assert intel.ladder[0].valid_until == "2026-12-31"


def test_onpage_records_embeds_forms_chat_pdfs_not_invented():
    from app.omni.onpage import analyse_onpage, classify_embed
    assert classify_embed("https://www.youtube.com/embed/abc") == "youtube"
    assert classify_embed("https://docs.google.com/document/d/x") is None
    html = """<html><body>
    <iframe src="https://www.youtube.com/embed/abc"></iframe>
    <form action="/signup"></form>
    <a href="https://wa.me/919999999999">Chat</a>
    <a href="/files/price.pdf">Price list</a>
    <a href="https://other.com/x.pdf">Off-host</a>
    </body></html>"""
    intel = analyse_onpage([("https://acme.example/", html)])
    assert intel.assessed is True
    kinds = {(h.kind, h.provider) for h in intel.hits}
    assert ("embed", "youtube") in kinds
    assert ("form", "first_party") in kinds
    assert ("chat", "whatsapp") in kinds
    assert ("pdf", "same_host") in kinds
    assert ("pdf", "off_host") in kinds
    assert not any(h.url.endswith("/brochure.pdf") for h in intel.hits)
    empty = analyse_onpage([("https://acme.example/", "<html><p>hello</p></html>")])
    assert empty.assessed is True
    assert empty.hits == []


def test_gstin_input_is_hard_id_not_a_name():
    from app.omni.resolve import KIND_GSTIN, KIND_NAME, identifiers_from_input
    rows = identifiers_from_input("keyword", "27AAPFU0939F1ZV")
    assert len(rows) == 1 and rows[0].kind == KIND_GSTIN
    name_only = identifiers_from_input("keyword", "Acme Software")
    assert name_only and name_only[0].kind == KIND_NAME


def test_watch_diff_sees_h1_and_feed():
    from app.omni.watch import diff_homepage
    prev = {"title": "Acme", "h1": "Hello", "tech": [], "socials": [],
            "feed_title": "Old", "feed_published": "2026-01-01"}
    curr = {"title": "Acme", "h1": "Hello world", "tech": [], "socials": [],
            "feed_title": "New", "feed_published": "2026-08-01"}
    kinds = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage H1 changed" in kinds
    assert "Latest first-party feed item changed" in kinds


def test_locale_from_tags_not_body_copy():
    from app.omni.locale import analyse_locale
    html = """<html lang="en-IN">
    <head><meta property="og:locale" content="en_IN"></head>
    <body>We target Hindi speakers across hi-IN markets.</body></html>"""
    page = extract_page("https://acme.example/", html)
    intel = analyse_locale(
        [page],
        hreflang=[{"lang": "hi-IN", "url": "https://acme.example/hi/"}],
        content_language="en",
    )
    assert intel.assessed is True
    assert intel.langs == ["en-IN"]
    assert intel.og_locales == ["en-IN"]
    assert intel.hreflang == ["hi-IN"]
    assert intel.content_language == "en"
    assert "Hindi" not in intel.langs
    blank = analyse_locale([extract_page(
        "https://acme.example/",
        "<html><body>English only for India</body></html>")])
    assert blank.assessed is True
    assert blank.langs == []
    assert blank.og_locales == []


def test_software_application_os_from_field():
    from app.omni.schema_intel import analyse_schema
    html = """<html><head><script type="application/ld+json">
    {"@graph":[
      {"@type":"SoftwareApplication","name":"Acme iOS",
       "operatingSystem":"iOS"},
      {"@type":"MobileApplication","name":"Acme Android",
       "operatingSystem":"Android"}
    ]}
    </script></head><body>Available on Windows and Linux.</body></html>"""
    intel = analyse_schema([("https://acme.example/", html)])
    by_name = {a.name: a for a in intel.apps}
    assert by_name["Acme iOS"].kind == "software"
    assert by_name["Acme iOS"].os == "iOS"
    assert by_name["Acme Android"].kind == "mobile"
    assert by_name["Acme Android"].os == "Android"
    assert not any("Windows" in (a.os or "") for a in intel.apps)


def test_return_days_from_schema_not_invented():
    from app.omni.products import commerce_policies
    html = """<html><head><script type="application/ld+json">
    {"@type":"Product","name":"Acme Pro",
     "offers":{"hasMerchantReturnPolicy":{
         "merchantReturnDays":7,
         "returnPolicyCategory":"https://schema.org/MerchantReturnFiniteReturnWindow"},
       "shippingDetails":{"shippingDestination":{"name":"India"}}}}
    </script></head><body>Free 90-day returns worldwide.</body></html>"""
    rows = commerce_policies([("https://acme.example/", html)])
    kinds = {r["kind"]: r for r in rows}
    assert "7 merchantReturnDays" in kinds["return"]["detail"]
    assert "90" not in kinds["return"]["detail"]
    assert kinds["shipping"]["detail"] == "India"
    assert "worldwide" not in kinds["shipping"]["detail"]
    blank = commerce_policies([("https://acme.example/",
                                "<html><body>Free 90-day returns.</body></html>")])
    assert blank == []


def test_watch_diff_lang_types_headers():
    from app.omni.watch import diff_homepage, snapshot_from_html
    prev_html = """<html lang="en"><head>
    <script type="application/ld+json">{"@type":"Organization","name":"Acme"}</script>
    </head><body><h1>Hi</h1></body></html>"""
    curr_html = """<html lang="hi"><head>
    <meta property="og:locale" content="hi_IN">
    <script type="application/ld+json">{"@type":"FAQPage"}</script>
    </head><body><h1>Hi</h1></body></html>"""
    prev = snapshot_from_html(
        "https://acme.example/", prev_html,
        headers={"strict-transport-security": "max-age=1"})
    curr = snapshot_from_html(
        "https://acme.example/", curr_html,
        headers={"content-security-policy": "default-src 'self'"})
    assert prev["lang"] == "en"
    assert curr["lang"] == "hi"
    titles = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage html lang changed" in titles
    assert "Homepage JSON-LD types changed" in titles
    assert "Homepage security headers changed" in titles


def test_digest_legal_date_and_printed_valid_until():
    import json
    from datetime import datetime, timedelta

    from sqlmodel import Session, SQLModel, create_engine

    from app.models import Report
    from app.omni.digest import build

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    now = datetime.utcnow()
    in_window = now.date().isoformat()
    payload = {
        "legal_intel": {"assessed": True, "policies": [
            {"kind": "privacy", "title": "Privacy", "updated": in_window,
             "url": "https://acme.example/privacy"},
        ]},
        "product_intel": {"ladder": [
            {"name": "Acme Pro", "valid_until": in_window,
             "url": "https://acme.example/pro"},
        ]},
        "schema_intel": {"articles": [
            {"title": "Old recap", "published": "2020-01-01"},
        ]},
    }
    with Session(engine) as s:
        s.add(Report(
            id="r1", job_id="j1", share_slug="acme-r1", subject_name="Acme",
            subject_handle="", seed_url="https://acme.example/",
            html_path="/tmp/x.html", kind="web",
            payload_json=json.dumps(payload), created_at=now))
        s.commit()
        intel = build(s, None, days=7)
        titles = [i.title for i in intel.items]
        kinds = {i.kind for i in intel.items}
        assert "legal" in kinds
        assert "offer" in kinds
        assert "Privacy" in titles
        assert "Acme Pro" in titles
        assert "Old recap" not in titles
        assert any("not an expiry" in i.detail for i in intel.items if i.kind == "offer")
        far = Report(
            id="r2", job_id="j2", share_slug="acme-r2", subject_name="Beta",
            subject_handle="", seed_url="https://beta.example/",
            html_path="/tmp/y.html", kind="web",
            payload_json=json.dumps({
                "product_intel": {"ladder": [
                    {"name": "Future", "valid_until": (now + timedelta(days=400)
                                                       ).date().isoformat()},
                ]},
            }), created_at=now)
        s.add(far)
        s.commit()
        later = build(s, None, days=7)
        assert not any(i.title == "Future" for i in later.items)


def test_catalog_ids_from_schema_not_rupee_copy():
    from app.omni.products import catalog_ids
    html = """<html><head><script type="application/ld+json">
    {"@type":"Product","name":"Acme Pro","sku":"ACME-1","gtin13":"8901234567890",
     "brand":{"@type":"Brand","name":"Acme"},
     "offers":{"price":"4999","priceCurrency":"INR"}}
    </script></head><body>SKU ₹4,999 on the shelf.</body></html>"""
    rows = catalog_ids([("https://acme.example/", html)])
    kinds = {r["kind"]: r["value"] for r in rows}
    assert kinds["sku"] == "ACME-1"
    assert kinds["gtin"] == "8901234567890"
    assert kinds["brand"] == "Acme"
    assert "4999" not in kinds.values()
    assert "₹4,999" not in kinds.values()
    blank = catalog_ids([("https://acme.example/",
                          "<html><body>SKU ₹4,999</body></html>")])
    assert blank == []


def test_indexability_from_meta_not_body_copy():
    from app.omni.indexability import analyse_indexability, tokens_from_page
    html = """<html><head>
    <meta name="robots" content="noindex, nofollow">
    </head><body>Please noindex this draft forever.</body></html>"""
    intel = analyse_indexability(
        [("https://acme.example/draft", html)],
        headers={"x-robots-tag": "nosnippet"})
    assert intel.assessed is True
    assert intel.noindex == ["https://acme.example/draft"]
    assert "nofollow" in intel.pages[0].tokens
    assert any(p.source == "header" and "nosnippet" in p.tokens for p in intel.pages)
    assert tokens_from_page(html, None) == ["noindex", "nofollow"]
    empty = analyse_indexability([
        ("https://acme.example/", "<html><body>Add noindex please</body></html>")])
    assert empty.assessed is True
    assert empty.pages == []
    assert empty.noindex == []


def test_http_date_and_header_freshness():
    from app.omni.site import from_headers, parse_http_date
    assert parse_http_date("Wed, 19 Aug 2026 10:00:00 GMT") == "2026-08-19"
    assert parse_http_date("2026-08-01T12:00:00Z") == "2026-08-01"
    assert parse_http_date("not a date") == ""
    intel = from_headers({
        "Last-Modified": "Wed, 19 Aug 2026 10:00:00 GMT",
        "ETag": '"abc"',
        "Cache-Control": "max-age=60",
        "X-Robots-Tag": "noindex",
        "Strict-Transport-Security": "max-age=1",
    })
    assert intel.last_modified.startswith("Wed, 19 Aug 2026")
    assert intel.etag == '"abc"'
    assert intel.cache_control == "max-age=60"
    assert intel.x_robots_tag == "noindex"
    assert "strict-transport-security" in intel.present
    assert "content-security-policy" in intel.missing


def test_watch_diff_etag_lastmod_robots():
    from app.omni.watch import diff_homepage, snapshot_from_html
    html = """<html><head><meta name="robots" content="index, follow">
    </head><body><h1>Hi</h1></body></html>"""
    blocked = """<html><head><meta name="robots" content="noindex">
    </head><body><h1>Hi</h1></body></html>"""
    prev = snapshot_from_html(
        "https://acme.example/", html,
        headers={"etag": '"1"', "last-modified": "Wed, 12 Aug 2026 10:00:00 GMT"})
    curr = snapshot_from_html(
        "https://acme.example/", blocked,
        headers={"etag": '"2"', "last-modified": "Wed, 19 Aug 2026 10:00:00 GMT"})
    titles = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage ETag changed" in titles
    assert "Homepage Last-Modified changed" in titles
    assert "Homepage robots directives changed" in titles


def test_digest_last_modified_in_window():
    import json
    from datetime import datetime

    from sqlmodel import Session, SQLModel, create_engine

    from app.models import Report
    from app.omni.digest import build

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    now = datetime.utcnow()
    payload = {
        "header_intel": {
            "last_modified": now.date().isoformat(),
        },
    }
    with Session(engine) as s:
        s.add(Report(
            id="r1", job_id="j1", share_slug="acme-r1", subject_name="Acme",
            subject_handle="", seed_url="https://acme.example/",
            html_path="/tmp/x.html", kind="web",
            payload_json=json.dumps(payload), created_at=now))
        s.commit()
        intel = build(s, None, days=7)
        assert any(i.kind == "freshness" and "Last-Modified" in i.title
                   for i in intel.items)
        assert any("not a verified edit" in i.detail for i in intel.items
                   if i.kind == "freshness")


def test_ads_txt_parses_iab_rows_not_html_or_copy():
    from app.omni.ads import parse_ads_txt, summarise
    body = (
        "# comment\n"
        "OWNERDOMAIN=acme.example\n"
        "google.com, pub-123, DIRECT, f08c47fec0942fa0\n"
        "example.com, abc, RESELLER\n"
        "not-a-row\n"
        "We buy Google Ads every day\n"
    )
    rows, variables = parse_ads_txt(body, "/ads.txt")
    assert rows[0].exchange == "google.com"
    assert rows[0].relationship == "DIRECT"
    assert rows[0].publisher == "pub-123"
    assert rows[1].relationship == "RESELLER"
    assert variables[0].key == "ownerdomain"
    html_rows, _ = parse_ads_txt(
        "<html><body>google.com, pub-123, DIRECT</body></html>", "/ads.txt")
    assert html_rows == []
    empty = summarise([], [], [])
    assert empty.assessed is True
    assert empty.rows == []
    assert "no ads.txt" in empty.reason.lower()


def test_claims_from_meta_and_rel_me_not_body_copy():
    from app.omni.claims import analyse_claims
    html = """<html><head>
    <meta name="google-site-verification" content="token-is-not-stored">
    <link rel="me" href="https://github.com/acme">
    </head><body>Add google-site-verification and rel=me in the footer.</body></html>"""
    intel = analyse_claims([("https://acme.example/", html)])
    assert intel.verifications == ["google"]
    assert intel.rel_me[0].host == "github.com"
    assert not any("token-is-not-stored" in (m.url or "") for m in intel.rel_me)
    blank = analyse_claims([("https://acme.example/",
                             "<html><body>google-site-verification rel=me</body></html>")])
    assert blank.verifications == []
    assert blank.rel_me == []
    assert blank.same_as == []


def test_watch_diff_verification_and_rel_me():
    from app.omni.watch import diff_homepage, snapshot_from_html
    prev_html = "<html><head></head><body><h1>Hi</h1></body></html>"
    curr_html = """<html><head>
    <meta name="facebook-domain-verification" content="x">
    <link rel="me" href="https://mastodon.social/@acme">
    </head><body><h1>Hi</h1></body></html>"""
    prev = snapshot_from_html("https://acme.example/", prev_html)
    curr = snapshot_from_html("https://acme.example/", curr_html)
    titles = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage verification meta changed" in titles
    assert "Homepage rel=me links changed" in titles
    assert "facebook" in curr["verifications"]
    assert "mastodon.social" in curr["rel_me"]


def test_cards_from_meta_not_body_copy():
    from app.omni.cards import analyse_cards

    html = (
        "<html><head>"
        '<meta property="og:type" content="article"/>'
        '<meta name="twitter:site" content="@acme"/>'
        '<meta name="twitter:card" content="summary_large_image"/>'
        '<meta name="apple-itunes-app" content="app-id=12345"/>'
        "</head><body>follow @acme and we have an app</body></html>"
    )
    intel = analyse_cards([("https://acme.example/", html)])
    assert intel.og_type == "article"
    assert intel.twitter_site == "@acme"
    assert intel.twitter_card == "summary_large_image"
    assert intel.banners[0].kind == "ios"
    assert intel.banners[0].value == "app-id=12345"
    empty = analyse_cards([("https://acme.example/",
                            "<html><body>follow @acme</body></html>")])
    assert empty.assessed is True
    assert empty.twitter_site == ""
    assert empty.banners == []


def test_vendors_from_script_src_not_body_copy():
    from app.omni.vendors import analyse_vendors

    html = (
        '<html><head><script src="https://js.hubspot.com/v2.js"></script>'
        '<link rel="preconnect" href="https://fonts.gstatic.com"/>'
        "</head><body>we use HubSpot and Google Fonts</body></html>"
    )
    intel = analyse_vendors([("https://acme.example/", html)])
    assert "js.hubspot.com" in intel.unique
    assert "fonts.gstatic.com" in intel.unique
    empty = analyse_vendors([
        ("https://acme.example/",
         "<html><body>we use HubSpot and Google Fonts</body></html>"),
    ])
    assert empty.unique == []
    assert empty.assessed is True


def test_job_salary_and_event_offer_from_schema_not_body():
    from app.omni.schema_intel import analyse_schema

    html = """<html><head><script type="application/ld+json">{
      "@context": "https://schema.org",
      "@graph": [
        {"@type": "JobPosting", "title": "Engineer",
         "validThrough": "2026-12-01",
         "baseSalary": {"@type": "MonetaryAmount", "currency": "INR",
           "value": {"@type": "QuantitativeValue", "minValue": 1000000,
                     "maxValue": 2000000, "unitText": "YEAR"}}},
        {"@type": "Event", "name": "Launch", "startDate": "2026-09-01",
         "offers": {"@type": "Offer", "price": "499", "priceCurrency": "INR"}}
      ]
    }</script></head><body>20 LPA tickets from 99</body></html>"""
    intel = analyse_schema([("https://acme.example/", html)])
    assert intel.jobs[0].salary == "1000000-2000000 INR YEAR"
    assert intel.jobs[0].valid_through == "2026-12-01"
    assert intel.events[0].offer == "499 INR"
    assert intel.events[0].start == "2026-09-01"
    assert "20 LPA" not in intel.jobs[0].salary
    assert "tickets" not in intel.events[0].offer


def test_watch_diffs_twitter_site_og_type_and_vendors():
    from app.omni.watch import diff_homepage, snapshot_from_html

    prev_html = (
        "<html><head>"
        '<meta property="og:type" content="website"/>'
        '<meta name="twitter:site" content="@old"/>'
        '<script src="https://js.hubspot.com/v2.js"></script>'
        "</head></html>"
    )
    curr_html = (
        "<html><head>"
        '<meta property="og:type" content="article"/>'
        '<meta name="twitter:site" content="@new"/>'
        '<script src="https://www.googletagmanager.com/gtm.js"></script>'
        "</head></html>"
    )
    prev = snapshot_from_html("https://acme.example/", prev_html)
    curr = snapshot_from_html("https://acme.example/", curr_html)
    titles = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage twitter:site changed" in titles
    assert "Homepage og:type changed" in titles
    assert "Homepage third-party hosts changed" in titles
    assert curr["twitter_site"] == "@new"
    assert curr["og_type"] == "article"
    assert "googletagmanager.com" in curr["vendors"]
    assert "js.hubspot.com" not in curr["vendors"]


def test_digest_includes_job_valid_through_and_event_start():
    import json
    from datetime import datetime

    from sqlmodel import Session, SQLModel, create_engine

    from app.models import Report
    from app.omni.digest import build

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    now = datetime.utcnow()
    in_window = now.date().isoformat()
    payload = {
        "schema_intel": {
            "jobs": [{"title": "Eng", "valid_through": in_window}],
            "events": [{"name": "Launch", "start": in_window}],
        },
    }
    with Session(engine) as session:
        session.add(Report(
            id="r-job", job_id="j-job", share_slug="acme-job",
            subject_name="Acme", subject_handle="",
            seed_url="https://acme.example/", html_path="/tmp/z.html",
            kind="web", payload_json=json.dumps(payload), created_at=now))
        session.commit()
        digest = build(session, None, days=7)
    kinds = {item.kind for item in digest.items}
    titles = [item.title for item in digest.items]
    assert "job" in kinds
    assert "event" in kinds
    assert "Eng" in titles
    assert "Launch" in titles
    assert any("not a hiring deadline" in item.detail
               for item in digest.items if item.kind == "job")


def test_document_links_from_rel_not_body_copy():
    from app.omni.links import analyse_links

    html = (
        "<html><head>"
        '<link rel="canonical" href="https://acme.example/home"/>'
        '<link rel="manifest" href="/manifest.json"/>'
        '<link rel="author" href="https://authors.example/jane"/>'
        '<link rel="stylesheet" href="https://fonts.gstatic.com/x.css"/>'
        "</head><body>see /manifest.json and the author page</body></html>"
    )
    intel = analyse_links([("https://acme.example/", html)])
    rels = {row.rel: row.url for row in intel.rows}
    assert rels["canonical"] == "https://acme.example/home"
    assert rels["manifest"].endswith("/manifest.json")
    assert rels["author"] == "https://authors.example/jane"
    assert "stylesheet" not in rels
    assert intel.canonical == "https://acme.example/home"
    empty = analyse_links([("https://acme.example/",
                            "<html><body>see /manifest.json author</body></html>")])
    assert empty.assessed is True
    assert empty.rows == []
    assert empty.canonical == ""


def test_http_link_header_not_invented_from_body():
    from app.omni.links import analyse_links

    intel = analyse_links(
        [("https://acme.example/", "<html><body>Link: manifest</body></html>")],
        headers={"Link": '<https://acme.example/manifest.json>; rel="manifest"'},
    )
    assert intel.manifests == ["https://acme.example/manifest.json"]
    assert intel.rows[0].via == "header"
    blank = analyse_links(
        [("https://acme.example/", "<html><body>Link: manifest</body></html>")],
        headers={},
    )
    assert blank.manifests == []


def test_csp_hosts_from_header_not_body_or_keywords():
    from app.omni.site import from_headers, parse_csp_hosts

    hosts = parse_csp_hosts(
        "default-src 'self'; script-src 'self' https://cdn.example.com "
        "'unsafe-inline'; img-src https:; connect-src wss: https://acme.example",
        origin="acme.example",
    )
    assert hosts == ["cdn.example.com"]
    intel = from_headers({
        "Content-Security-Policy": "script-src https://js.stripe.com",
        "Strict-Transport-Security": "max-age=1",
    }, origin="acme.example")
    assert intel.csp_hosts == ["js.stripe.com"]
    empty = from_headers({
        "Strict-Transport-Security": "max-age=1",
    }, origin="acme.example")
    assert empty.csp_hosts == []


def test_watch_diffs_canonical_links_and_csp():
    from app.omni.watch import diff_homepage, snapshot_from_html

    prev = snapshot_from_html(
        "https://acme.example/",
        '<html><head><link rel="canonical" href="https://acme.example/old"/></head></html>',
        headers={"content-security-policy": "script-src https://js.hubspot.com"},
    )
    curr = snapshot_from_html(
        "https://acme.example/",
        '<html><head><link rel="canonical" href="https://acme.example/new"/>'
        '<link rel="author" href="https://authors.example/jane"/></head></html>',
        headers={"content-security-policy": "script-src https://js.stripe.com"},
    )
    titles = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage canonical changed" in titles
    assert "Homepage document links changed" in titles
    assert "Homepage CSP hosts changed" in titles
    assert curr["canonical"] == "https://acme.example/new"
    assert "js.stripe.com" in curr["csp_hosts"]
    assert "js.hubspot.com" not in curr["csp_hosts"]


def test_article_date_modified_separate_from_published_and_body():
    from app.omni.schema_intel import analyse_schema

    html = """<html><head><script type="application/ld+json">{
      "@type":"BlogPosting","headline":"Launch notes",
      "datePublished":"2026-01-01","dateModified":"2026-08-19"
    }</script></head><body>Updated yesterday — 2024 recap</body></html>"""
    intel = analyse_schema([("https://acme.example/blog", html)])
    assert intel.articles[0].published == "2026-01-01"
    assert intel.articles[0].modified == "2026-08-19"
    blank = analyse_schema([("https://acme.example/blog",
                             "<html><body>Updated yesterday dateModified</body></html>")])
    assert blank.articles == []


def test_course_from_schema_not_body_copy():
    from app.omni.schema_intel import analyse_schema

    html = """<html><head><script type="application/ld+json">{
      "@type":"Course","name":"Growth Lab",
      "provider":{"@type":"Organization","name":"Acme Academy"},
      "courseCode":"GL-1",
      "educationalCredentialAwarded":"Certificate",
      "hasCourseInstance":{"@type":"CourseInstance","startDate":"2026-09-01"}
    }</script></head><body>Join our Masterclass tomorrow. 10,000 students.</body></html>"""
    intel = analyse_schema([("https://acme.example/learn", html)])
    assert intel.courses[0].name == "Growth Lab"
    assert intel.courses[0].kind == "course"
    assert intel.courses[0].provider == "Acme Academy"
    assert intel.courses[0].code == "GL-1"
    assert intel.courses[0].start == "2026-09-01"
    assert intel.courses[0].credential == "Certificate"
    empty = analyse_schema([("https://acme.example/learn",
                             "<html><body>Join our Masterclass. 10,000 students.</body></html>")])
    assert empty.courses == []


def test_digest_includes_date_modified_and_course_start():
    import json
    from datetime import datetime

    from sqlmodel import Session, SQLModel, create_engine

    from app.models import Report
    from app.omni.digest import build

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    now = datetime.utcnow()
    in_window = now.date().isoformat()
    payload = {
        "schema_intel": {
            "articles": [{
                "title": "Launch notes",
                "published": "2020-01-01",
                "modified": in_window,
            }],
            "courses": [{"name": "Growth Lab", "start": in_window}],
        },
    }
    with Session(engine) as session:
        session.add(Report(
            id="r-mod", job_id="j-mod", share_slug="acme-mod",
            subject_name="Acme", subject_handle="",
            seed_url="https://acme.example/", html_path="/tmp/m.html",
            kind="web", payload_json=json.dumps(payload), created_at=now))
        session.commit()
        digest = build(session, None, days=7)
    titles = [item.title for item in digest.items]
    kinds = {item.kind for item in digest.items}
    assert "Launch notes" in titles
    assert "Growth Lab" in titles
    assert "course" in kinds
    assert any("dateModified" in item.detail for item in digest.items
               if item.title == "Launch notes")
    assert not any(item.at.startswith("2020-01-01") for item in digest.items)


def test_watch_diffs_article_modified_and_courses():
    from app.omni.watch import diff_homepage, snapshot_from_html

    prev_html = """<html><head><script type="application/ld+json">{
      "@graph":[
        {"@type":"BlogPosting","headline":"Notes","dateModified":"2026-01-01"},
        {"@type":"Course","name":"Old Lab"}
      ]
    }</script></head></html>"""
    curr_html = """<html><head><script type="application/ld+json">{
      "@graph":[
        {"@type":"BlogPosting","headline":"Notes","dateModified":"2026-08-19"},
        {"@type":"Course","name":"Growth Lab"}
      ]
    }</script></head></html>"""
    prev = snapshot_from_html("https://acme.example/", prev_html)
    curr = snapshot_from_html("https://acme.example/", curr_html)
    titles = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage article dateModified changed" in titles
    assert "Homepage course schema changed" in titles
    assert curr["article_modified"] == "2026-08-19"
    assert "Growth Lab" in curr["courses"]
    assert "Old Lab" not in curr["courses"]


def test_contact_point_from_schema_not_body_copy():
    from app.omni.schema_intel import analyse_schema

    html = """<html><head><script type="application/ld+json">{
      "@type":"Organization","name":"Acme",
      "contactPoint":{"@type":"ContactPoint","contactType":"customer support",
                      "telephone":"+91-80-1234","email":"help@acme.example",
                      "areaServed":"IN"}
    }</script></head><body>Call support at our India desk anytime.</body></html>"""
    intel = analyse_schema([("https://acme.example/", html)])
    assert intel.contact_points[0].contact_type == "customer support"
    assert intel.contact_points[0].telephone == "+91-80-1234"
    assert intel.contact_points[0].email == "help@acme.example"
    assert intel.contact_points[0].area == "IN"
    empty = analyse_schema([("https://acme.example/",
                             "<html><body>Call support at our India desk.</body></html>")])
    assert empty.contact_points == []


def test_item_list_from_schema_not_body_or_breadcrumbs():
    from app.omni.schema_intel import analyse_schema

    html = """<html><head><script type="application/ld+json">{
      "@graph":[
        {"@type":"ItemList","name":"Catalog","numberOfItems":2,
         "itemListElement":[
           {"@type":"ListItem","position":1,"name":"Acme Pro"},
           {"@type":"ListItem","position":2,"item":{"name":"Acme Lite"}}
         ]},
        {"@type":"BreadcrumbList","itemListElement":[
          {"@type":"ListItem","position":1,"name":"Home"}
        ]}
      ]
    }</script></head><body>Catalog: Acme Ultra and 50 SKUs.</body></html>"""
    intel = analyse_schema([("https://acme.example/shop", html)])
    assert len(intel.item_lists) == 1
    assert intel.item_lists[0].name == "Catalog"
    assert intel.item_lists[0].entries == ["Acme Pro", "Acme Lite"]
    assert intel.item_lists[0].number_of_items == "2"
    assert "Acme Ultra" not in intel.item_lists[0].entries
    assert intel.breadcrumbs[0].path == "Home"
    assert intel.offer_catalogs == []


def test_watch_diffs_contact_points_and_item_lists():
    from app.omni.watch import diff_homepage, snapshot_from_html

    prev_html = """<html><head><script type="application/ld+json">{
      "@graph":[
        {"@type":"ContactPoint","contactType":"sales","telephone":"+1-1"},
        {"@type":"ItemList","name":"Old catalog","itemListElement":[{"name":"A"}]}
      ]
    }</script></head></html>"""
    curr_html = """<html><head><script type="application/ld+json">{
      "@graph":[
        {"@type":"ContactPoint","contactType":"support","telephone":"+1-2"},
        {"@type":"ItemList","name":"New catalog","itemListElement":[{"name":"B"}]}
      ]
    }</script></head></html>"""
    prev = snapshot_from_html("https://acme.example/", prev_html)
    curr = snapshot_from_html("https://acme.example/", curr_html)
    titles = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage ContactPoint changed" in titles
    assert "Homepage ItemList changed" in titles
    assert "support" in curr["contact_points"]
    assert "New catalog" in curr["item_lists"]


def test_aggregate_offer_from_schema_not_body_copy():
    from app.omni.schema_intel import analyse_schema

    html = """<html><head><script type="application/ld+json">{
      "@type":"Product","name":"Acme Pro",
      "offers":{"@type":"AggregateOffer","lowPrice":"99","highPrice":"499",
                "priceCurrency":"INR","offerCount":3}
    }</script></head><body>Plans from ₹49. 20 SKUs on the shelf.</body></html>"""
    intel = analyse_schema([("https://acme.example/pricing", html)])
    row = intel.aggregate_offers[0]
    assert row.name == "Acme Pro"
    assert row.low == "99"
    assert row.high == "499"
    assert row.currency == "INR"
    assert row.offer_count == "3"
    assert "49" not in {row.low, row.high, row.offer_count}
    empty = analyse_schema([("https://acme.example/pricing",
                             "<html><body>Plans from ₹49. 20 SKUs.</body></html>")])
    assert empty.aggregate_offers == []


def test_offer_catalog_from_schema_not_body_copy():
    from app.omni.schema_intel import analyse_schema

    html = """<html><head><script type="application/ld+json">{
      "@type":"Organization","name":"Acme",
      "hasOfferCatalog":{"@type":"OfferCatalog","name":"Plans",
        "itemListElement":[
          {"@type":"Offer","itemOffered":{"name":"Starter"}},
          {"@type":"Offer","name":"Growth"}
        ]}
    }</script></head><body>Plans: Ultra and Enterprise.</body></html>"""
    intel = analyse_schema([("https://acme.example/", html)])
    assert intel.offer_catalogs[0].name == "Plans"
    assert intel.offer_catalogs[0].items == ["Starter", "Growth"]
    assert "Ultra" not in intel.offer_catalogs[0].items
    empty = analyse_schema([("https://acme.example/",
                             "<html><body>Plans: Ultra and Enterprise.</body></html>")])
    assert empty.offer_catalogs == []


def test_watch_diffs_aggregate_offer_and_offer_catalog():
    from app.omni.watch import diff_homepage, snapshot_from_html

    prev_html = """<html><head><script type="application/ld+json">{
      "@graph":[
        {"@type":"AggregateOffer","name":"Old","lowPrice":"10","highPrice":"20"},
        {"@type":"OfferCatalog","name":"Old plans","itemListElement":[{"name":"A"}]}
      ]
    }</script></head></html>"""
    curr_html = """<html><head><script type="application/ld+json">{
      "@graph":[
        {"@type":"AggregateOffer","name":"New","lowPrice":"99","highPrice":"499"},
        {"@type":"OfferCatalog","name":"New plans","itemListElement":[{"name":"B"}]}
      ]
    }</script></head></html>"""
    prev = snapshot_from_html("https://acme.example/", prev_html)
    curr = snapshot_from_html("https://acme.example/", curr_html)
    titles = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage AggregateOffer changed" in titles
    assert "Homepage OfferCatalog changed" in titles
    assert any("New:99-499" in x for x in curr["aggregate_offers"])
    assert "New plans" in curr["offer_catalogs"]


def test_speakable_from_schema_not_body_copy():
    from app.omni.schema_intel import analyse_schema

    html = """<html><head><script type="application/ld+json">{
      "@type":"WebPage","name":"Home",
      "speakable":{"@type":"SpeakableSpecification",
                   "cssSelector":[".lead","#summary"],
                   "xpath":"/html/body/h1"}
    }</script></head><body>This page is speakable for voice search.</body></html>"""
    intel = analyse_schema([("https://acme.example/", html)])
    assert intel.speakable[0].selectors == [
        "cssSelector:.lead", "cssSelector:#summary", "xpath:/html/body/h1"]
    empty = analyse_schema([("https://acme.example/",
                             "<html><body>This page is speakable.</body></html>")])
    assert empty.speakable == []


def test_webpage_last_reviewed_and_significant_link_not_body_or_crawl():
    from app.omni.schema_intel import analyse_schema

    html = """<html><head><script type="application/ld+json">{
      "@graph":[
        {"@type":"WebPage","name":"Home"},
        {"@type":"AboutPage","name":"About","lastReviewed":"2026-08-19T09:00:00Z",
         "reviewedBy":{"@type":"Person","name":"Jane"},
         "specialty":"Pricing",
         "significantLink":["/team","https://acme.example/careers"]}
      ]
    }</script></head><body>last reviewed yesterday. significantLink /secret</body></html>"""
    intel = analyse_schema([("https://acme.example/", html)])
    assert len(intel.web_pages) == 1
    row = intel.web_pages[0]
    assert row.name == "About"
    assert row.kind == "AboutPage"
    assert row.last_reviewed == "2026-08-19"
    assert row.reviewed_by == "Jane"
    assert row.specialty == "Pricing"
    assert row.significant_links == [
        "https://acme.example/team", "https://acme.example/careers"]
    assert not any("/secret" in href for href in row.significant_links)
    empty = analyse_schema([("https://acme.example/",
                             "<html><body>last reviewed yesterday</body></html>")])
    assert empty.web_pages == []


def test_digest_includes_last_reviewed():
    import json
    from datetime import datetime

    from sqlmodel import Session, SQLModel, create_engine

    from app.models import Report
    from app.omni.digest import build

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    now = datetime.utcnow()
    in_window = now.date().isoformat()
    payload = {
        "schema_intel": {
            "web_pages": [{
                "name": "About",
                "kind": "AboutPage",
                "last_reviewed": in_window,
            }, {
                "name": "Old about",
                "last_reviewed": "2020-01-01",
            }],
        },
    }
    with Session(engine) as session:
        session.add(Report(
            id="r-rev", job_id="j-rev", share_slug="acme-rev",
            subject_name="Acme", subject_handle="",
            seed_url="https://acme.example/", html_path="/tmp/r.html",
            kind="web", payload_json=json.dumps(payload), created_at=now))
        session.commit()
        digest = build(session, None, days=7)
    titles = [item.title for item in digest.items]
    kinds = {item.kind for item in digest.items}
    assert "About" in titles
    assert "Old about" not in titles
    assert "webpage" in kinds
    assert any("lastReviewed" in item.detail for item in digest.items
               if item.title == "About")


def test_watch_diffs_last_reviewed_and_speakable():
    from app.omni.watch import diff_homepage, snapshot_from_html

    prev_html = """<html><head><script type="application/ld+json">{
      "@graph":[
        {"@type":"WebPage","name":"Home","lastReviewed":"2026-01-01",
         "speakable":{"@type":"SpeakableSpecification","cssSelector":".old"}}
      ]
    }</script></head></html>"""
    curr_html = """<html><head><script type="application/ld+json">{
      "@graph":[
        {"@type":"WebPage","name":"Home","lastReviewed":"2026-08-19",
         "speakable":{"@type":"SpeakableSpecification","cssSelector":".lead"}}
      ]
    }</script></head></html>"""
    prev = snapshot_from_html("https://acme.example/", prev_html)
    curr = snapshot_from_html("https://acme.example/", curr_html)
    titles = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage lastReviewed changed" in titles
    assert "Homepage speakable changed" in titles
    assert curr["last_reviewed"] == "2026-08-19"
    assert any("cssSelector:.lead" in token for token in curr["speakable"])
    assert not any("cssSelector:.old" in token for token in curr["speakable"])


def test_same_as_from_schema_not_body_copy():
    from app.omni.claims import analyse_claims

    html = """<html><head><script type="application/ld+json">{
      "@graph":[
        {"@type":"Organization","name":"Acme",
         "sameAs":["https://www.instagram.com/acme","/team",
                   {"@id":"https://www.linkedin.com/company/acme"}]},
        {"@type":"Person","name":"Jane",
         "sameAs":"https://github.com/jane"}
      ]
    }</script></head><body>sameAs https://instagram.com/imposter</body></html>"""
    intel = analyse_claims([("https://acme.example/", html)])
    urls = {row.url for row in intel.same_as}
    hosts = {row.host for row in intel.same_as}
    assert "https://www.instagram.com/acme" in urls
    assert "https://acme.example/team" in urls
    assert "https://www.linkedin.com/company/acme" in urls
    assert "https://github.com/jane" in urls
    assert "instagram.com" in hosts
    assert "linkedin.com" in hosts
    assert "github.com" in hosts
    assert not any("imposter" in row.url for row in intel.same_as)
    via = {row.via for row in intel.same_as}
    assert "Organization" in via
    assert "Person" in via
    empty = analyse_claims([("https://acme.example/",
                             "<html><body>sameAs https://instagram.com/imposter</body></html>")])
    assert empty.same_as == []


def test_watch_diffs_same_as():
    from app.omni.watch import diff_homepage, snapshot_from_html

    prev_html = """<html><head><script type="application/ld+json">{
      "@type":"Organization","name":"Acme",
      "sameAs":["https://www.youtube.com/@acme"]
    }</script></head></html>"""
    curr_html = """<html><head><script type="application/ld+json">{
      "@type":"Organization","name":"Acme",
      "sameAs":["https://www.instagram.com/acme"]
    }</script></head></html>"""
    prev = snapshot_from_html("https://acme.example/", prev_html)
    curr = snapshot_from_html("https://acme.example/", curr_html)
    titles = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage sameAs changed" in titles
    assert "instagram.com" in curr["same_as"]
    assert "youtube.com" not in curr["same_as"]
    assert "youtube.com" in prev["same_as"]


def test_aggregate_rating_from_localbusiness_not_body_copy():
    from app.omni.reviews import analyse_reviews

    html = """<html><head><script type="application/ld+json">{
      "@graph":[
        {"@type":"LocalBusiness","name":"Acme Cafe",
         "aggregateRating":{"@type":"AggregateRating","ratingValue":4.6,
                            "reviewCount":88,"bestRating":5}},
        {"@type":"Product","name":"Blend",
         "aggregateRating":{"ratingValue":"3.0","ratingCount":2}}
      ]
    }</script></head><body>4.9 stars from 10,000 Google reviews.</body></html>"""
    intel = analyse_reviews([("https://acme.example/", html)], [])
    assert intel.assessed is True
    assert len(intel.ratings) == 2
    cafe = next(c for c in intel.ratings if c.name == "Acme Cafe")
    assert cafe.value == "4.6"
    assert cafe.count == "88"
    assert cafe.best == "5"
    assert cafe.via == "LocalBusiness"
    assert intel.aggregate_rating == 4.6
    assert intel.aggregate_count == 88
    assert intel.item_count == 0
    empty = analyse_reviews([("https://acme.example/",
                              "<html><body>4.9 stars from 10,000 reviews.</body></html>")], [])
    assert empty.assessed is False
    assert empty.ratings == []


def test_review_date_published_feeds_digest():
    import json
    from datetime import datetime

    from sqlmodel import Session, SQLModel, create_engine

    from app.models import Report
    from app.omni.digest import build
    from app.omni.reviews import analyse_reviews

    html = """<html><head><script type="application/ld+json">{
      "@type":"Review","reviewBody":"Too expensive and the interface is confusing",
      "author":{"name":"Sam"},"datePublished":"2026-08-19",
      "reviewRating":{"ratingValue":2}
    }</script></head></html>"""
    intel = analyse_reviews([("https://acme.example/reviews", html)], [])
    assert intel.items[0].published == "2026-08-19"
    assert intel.items[0].author == "Sam"

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    now = datetime.utcnow()
    in_window = now.date().isoformat()
    payload = {
        "review_intel": {
            "items": [{
                "author": "Sam",
                "body": "Too expensive",
                "published": in_window,
            }, {
                "author": "Old",
                "body": "Fine",
                "published": "2020-01-01",
            }],
        },
    }
    with Session(engine) as session:
        session.add(Report(
            id="r-revw", job_id="j-revw", share_slug="acme-revw",
            subject_name="Acme", subject_handle="",
            seed_url="https://acme.example/", html_path="/tmp/rv.html",
            kind="web", payload_json=json.dumps(payload), created_at=now))
        session.commit()
        digest = build(session, None, days=7)
    titles = [item.title for item in digest.items]
    kinds = {item.kind for item in digest.items}
    assert "Sam" in titles
    assert "Old" not in titles
    assert "review" in kinds


def test_watch_diffs_aggregate_rating():
    from app.omni.watch import diff_homepage, snapshot_from_html

    prev_html = """<html><head><script type="application/ld+json">{
      "@type":"LocalBusiness","name":"Acme Cafe",
      "aggregateRating":{"ratingValue":"4.1","reviewCount":10}
    }</script></head></html>"""
    curr_html = """<html><head><script type="application/ld+json">{
      "@type":"LocalBusiness","name":"Acme Cafe",
      "aggregateRating":{"ratingValue":"4.6","reviewCount":88}
    }</script></head></html>"""
    prev = snapshot_from_html("https://acme.example/", prev_html)
    curr = snapshot_from_html("https://acme.example/", curr_html)
    titles = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage aggregateRating changed" in titles
    assert any("4.6:88" in token for token in curr["ratings"])
    assert not any("4.1:10" in token for token in curr["ratings"])


def test_opening_hours_from_spec_not_body_or_compact_string():
    from app.omni.schema_intel import analyse_schema

    html = """<html><head><script type="application/ld+json">{
      "@type":"LocalBusiness","name":"Acme Cafe",
      "openingHoursSpecification":[
        {"@type":"OpeningHoursSpecification",
         "dayOfWeek":"https://schema.org/Monday","opens":"09:00","closes":"18:00",
         "validThrough":"2026-12-31"},
        {"@type":"OpeningHoursSpecification",
         "dayOfWeek":["Tuesday","Wednesday"],"opens":"10:00","closes":"16:00"}
      ]
    }</script></head><body>Open daily 8am till late. 24 hours.</body></html>"""
    intel = analyse_schema([("https://acme.example/", html)])
    days = {row.day: row for row in intel.hours}
    assert set(days) == {"Monday", "Tuesday", "Wednesday"}
    assert days["Monday"].opens == "09:00"
    assert days["Monday"].closes == "18:00"
    assert days["Monday"].valid_through == "2026-12-31"
    assert days["Tuesday"].opens == "10:00"
    assert "8am" not in {row.opens for row in intel.hours}
    empty = analyse_schema([("https://acme.example/",
                             "<html><body>Open daily 8am till late.</body></html>")])
    assert empty.hours == []


def test_digest_includes_hours_valid_through():
    import json
    from datetime import datetime

    from sqlmodel import Session, SQLModel, create_engine

    from app.models import Report
    from app.omni.digest import build

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    now = datetime.utcnow()
    in_window = now.date().isoformat()
    payload = {
        "schema_intel": {
            "hours": [
                {"day": "Monday", "valid_through": in_window},
                {"day": "Sunday", "valid_through": "2020-01-01"},
            ],
        },
    }
    with Session(engine) as session:
        session.add(Report(
            id="r-hrs", job_id="j-hrs", share_slug="acme-hrs",
            subject_name="Acme", subject_handle="",
            seed_url="https://acme.example/", html_path="/tmp/h.html",
            kind="web", payload_json=json.dumps(payload), created_at=now))
        session.commit()
        digest = build(session, None, days=7)
    titles = [item.title for item in digest.items]
    kinds = {item.kind for item in digest.items}
    assert "Monday" in titles
    assert "Sunday" not in titles
    assert "hours" in kinds


def test_watch_diffs_opening_hours():
    from app.omni.watch import diff_homepage, snapshot_from_html

    prev_html = """<html><head><script type="application/ld+json">{
      "@type":"LocalBusiness","name":"Acme Cafe",
      "openingHoursSpecification":{
        "dayOfWeek":"Monday","opens":"09:00","closes":"17:00"}
    }</script></head></html>"""
    curr_html = """<html><head><script type="application/ld+json">{
      "@type":"LocalBusiness","name":"Acme Cafe",
      "openingHoursSpecification":{
        "dayOfWeek":"Monday","opens":"10:00","closes":"18:00"}
    }</script></head></html>"""
    prev = snapshot_from_html("https://acme.example/", prev_html)
    curr = snapshot_from_html("https://acme.example/", curr_html)
    titles = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage opening hours changed" in titles
    assert "Monday:10:00-18:00" in curr["hours"]
    assert "Monday:09:00-17:00" not in curr["hours"]


def test_howto_tools_from_schema_not_body_or_steps():
    from app.omni.schema_intel import analyse_schema

    html = """<html><head><script type="application/ld+json">{
      "@type":"HowTo","name":"Swap the filter",
      "totalTime":"PT15M",
      "tool":[{"@type":"HowToTool","name":"Screwdriver"},
              {"@type":"HowToTool","name":"Pliers"}],
      "supply":{"@type":"HowToSupply","name":"Filter cartridge"},
      "step":[{"@type":"HowToStep","name":"Unscrew the cap"}]
    }</script></head><body>You'll need a laptop and 10 minutes.</body></html>"""
    intel = analyse_schema([("https://acme.example/help", html)])
    row = intel.howtos[0]
    assert row.name == "Swap the filter"
    assert row.steps == 1
    assert row.tools == ["Screwdriver", "Pliers"]
    assert row.supplies == ["Filter cartridge"]
    assert row.total_time == "PT15M"
    assert "laptop" not in row.tools
    assert "Unscrew the cap" not in row.tools
    empty = analyse_schema([("https://acme.example/help",
                             "<html><body>You'll need a laptop.</body></html>")])
    assert empty.howtos == []


def test_watch_diffs_howto_tools():
    from app.omni.watch import diff_homepage, snapshot_from_html

    prev_html = """<html><head><script type="application/ld+json">{
      "@type":"HowTo","name":"Swap the filter",
      "tool":{"@type":"HowToTool","name":"Coin"}
    }</script></head></html>"""
    curr_html = """<html><head><script type="application/ld+json">{
      "@type":"HowTo","name":"Swap the filter",
      "tool":{"@type":"HowToTool","name":"Screwdriver"}
    }</script></head></html>"""
    prev = snapshot_from_html("https://acme.example/", prev_html)
    curr = snapshot_from_html("https://acme.example/", curr_html)
    titles = {d["title"] for d in diff_homepage(prev, curr)}
    assert "Homepage HowTo tools changed" in titles
    assert "Screwdriver" in curr["howto_tools"]
    assert "Coin" not in curr["howto_tools"]
