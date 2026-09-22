"""Adversarial regression tests for the evidence and verification engine."""
from __future__ import annotations

import asyncio

from app.schemas import PlatformAccount, Product, RawProfile, SearchHit


def test_search_ensemble_merges_provider_consensus_and_tracking(monkeypatch):
    from app.engine.discovery import search as sm

    async def fake_one(provider, query, limit):
        url = ("https://www.example.com/profile?utm_source=x&a=1" if provider == "serper"
               else "https://example.com/profile?a=1&fbclid=y")
        return [SearchHit(query=query, title="Same person", url=url,
                          provider=provider, providers=[provider], rank=2)]

    monkeypatch.setattr(sm, "_available_providers", lambda: ["serper", "brave"])
    monkeypatch.setattr(sm, "_search_one", fake_one)
    hits = asyncio.run(sm.search("exact identity", limit=5))
    assert len(hits) == 1
    assert hits[0].url == "https://example.com/profile?a=1"
    assert set(hits[0].providers) == {"serper", "brave"}


def test_popularity_alone_can_never_prove_identity():
    from app.engine.discovery.verify import check

    verdict = check(platform="telegram", url="https://t.me/famousperson",
                    from_owned_link=False, probe_confirmed=False, probe_confidence=0,
                    subject_handle="differentperson", subject_name="Different Person",
                    followers=2_000_000, primary_followers=3_000_000, items=900)
    assert not verdict.accept
    assert "could not verify" in verdict.reason


def test_search_requires_matching_collected_page_evidence():
    from app.engine.discovery.verify import check

    accepted = check(platform="telegram", url="https://t.me/realhandle",
                     from_owned_link=False, probe_confirmed=False, probe_confidence=0,
                     search_confirmed=True, search_confidence=.82,
                     page_title="Real Person (@realhandle)", subject_handle="realhandle",
                     subject_name="Real Person")
    rejected = check(platform="telegram", url="https://t.me/namesake",
                     from_owned_link=False, probe_confirmed=False, probe_confidence=0,
                     search_confirmed=True, search_confidence=.82,
                     page_title="Another Human", subject_handle="realhandle",
                     subject_name="Real Person")
    assert accepted.accept and accepted.source == "search+content"
    assert not rejected.accept


def test_strong_indexed_identity_attributes_walled_profile_without_metrics():
    from app.engine.discovery.verify import check
    from app.engine.discovery.corroborate import enforce

    strong = check(
        platform="linkedin", url="https://linkedin.com/in/democreator",
        from_owned_link=False, probe_confirmed=False, probe_confidence=0,
        search_confirmed=True, search_confidence=.96,
        indexed_identity_match=True,
        subject_handle="democreator", subject_name="Demo Creator")
    weak = check(
        platform="linkedin", url="https://linkedin.com/in/a-namesake",
        from_owned_link=False, probe_confirmed=False, probe_confidence=0,
        search_confirmed=True, search_confidence=.89,
        indexed_identity_match=False,
        subject_handle="democreator", subject_name="Demo Creator")
    assert strong.accept and strong.source == "search_identity"
    assert "metrics remain withheld" in strong.reason
    assert not weak.accept and "authentication wall" in weak.reason

    seed = PlatformAccount(
        platform="instagram", handle="democreator",
        url="https://instagram.com/democreator/", display_name="Demo Creator",
        raw={"verified_via": "seed"})
    linkedin = PlatformAccount(
        platform="linkedin", handle="democreator",
        url="https://linkedin.com/in/democreator", needs_manual=True,
        raw={"verified_via": "search_identity"})
    raw = RawProfile(seed_url=seed.url, seed_platform="instagram",
                     seed_handle="democreator", display_name="Demo Creator",
                     accounts=[seed, linkedin])
    enforce(raw)
    assert linkedin.raw["identity_status"] == "accepted"
    assert linkedin.raw["identity_role"] == "primary"
    assert linkedin.raw["analysis_eligible"] is True


def test_same_name_different_handle_does_not_pass_search_promotion():
    from app.engine.discovery import dorks, expander

    hit = SearchHit(query="q", title="Real Person | Official",
                    url="https://instagram.com/a_different_person/",
                    snippet="Real Person creator", provider="test", providers=["test"], rank=1)
    score = expander._identity_score(hit, name="Real Person", handle="realhandle",
                                     dork=dorks.PLATFORM_DORKS[0])
    assert score < 0.68


def test_cross_linked_identity_scores_higher_than_unlinked_namesake():
    from app.engine.discovery.corroborate import audit

    seed = PlatformAccount(platform="instagram", handle="realperson",
                           url="https://instagram.com/realperson/",
                           display_name="Real Person",
                           external_links=["https://youtube.com/@differenthandle"])
    linked = PlatformAccount(platform="youtube", handle="differenthandle",
                             url="https://youtube.com/@differenthandle",
                             display_name="Real Person")
    namesake = PlatformAccount(platform="telegram", handle="randomchannel",
                               url="https://t.me/randomchannel",
                               display_name="Real Person")
    raw = RawProfile(seed_url=seed.url, seed_platform="instagram",
                     seed_handle="realperson", display_name="Real Person",
                     accounts=[seed, linked, namesake])
    rows = {x["platform"]: x for x in audit(raw)["accounts"]}
    assert rows["youtube"]["score"] > rows["telegram"]["score"]
    assert any("cross-linked" in s for s in rows["youtube"]["signals"])


def test_enforcer_withholds_low_evidence_discovered_surface():
    from app.engine.discovery.corroborate import enforce

    seed = PlatformAccount(platform="instagram", handle="alpha",
                           url="https://instagram.com/alpha/", display_name="Alpha One")
    wrong = PlatformAccount(platform="telegram", handle="unrelated",
                            url="https://t.me/unrelated", display_name="Someone Else",
                            raw={"verified_via": "content"})
    raw = RawProfile(seed_url=seed.url, seed_platform="instagram", seed_handle="alpha",
                     display_name="Alpha One", accounts=[seed, wrong])
    enforce(raw)
    assert [a.platform for a in raw.accounts] == ["instagram"]
    assert raw.rejected and "cross-source identity audit" in raw.rejected[0]["reason"]


def test_conflicting_public_offer_prices_are_withheld():
    from app.engine.discovery.corroborate import audit

    a = PlatformAccount(platform="website", handle="alpha", url="https://alpha.test",
                        display_name="Alpha One",
                        products=[Product(name="Career Accelerator", price_inr=1000,
                                          url="https://alpha.test/course")])
    b = PlatformAccount(platform="topmate", handle="alpha", url="https://topmate.io/alpha",
                        display_name="Alpha One",
                        products=[Product(name="Career Accelerator", price_inr=2500,
                                          url="https://topmate.io/alpha/course")])
    raw = RawProfile(seed_url=a.url, seed_platform="website", seed_handle="alpha",
                     display_name="Alpha One", accounts=[a, b])
    report = audit(raw)
    offer = next(x for x in report["claims"] if x["key"].startswith("offer:"))
    assert offer["status"] == "conflicted" and offer["value"] == "withheld"
    assert any(x["type"] == "product_price" for x in report["conflicts"])


def test_website_collector_reads_jsonld_crawls_public_pages_and_keeps_provenance(monkeypatch):
    from app.engine.collectors import web

    root = '''<html><head><meta property="og:title" content="Alpha One"></head><body>
    <a href="/about">About</a><script type="application/ld+json">{
      "@type":"Person","name":"Alpha One","sameAs":["https://instagram.com/alpha"]
    }</script></body></html>'''
    about = '''<html><body><script type="application/ld+json">{
      "@type":"Product","name":"Decision Lab","offers":{"price":"4999","priceCurrency":"INR","url":"https://alpha.test/buy"}
    }</script></body></html>'''

    class Fake:
        def __init__(self, url, text):
            self.url, self.final_url, self.text = url, url, text
            self.status, self.ok, self.blocked_by_robots = 200, True, False
            self.from_cache, self.fetched_at = False, "2026-08-06T00:00:00+00:00"
            self.content_sha256 = "abc"

    async def fake_fetch(url, **kwargs):
        return Fake(url, about if url.endswith("/about") else root)

    monkeypatch.setattr(web, "fetch", fake_fetch)
    account = asyncio.run(web.collect_website("https://alpha.test"))
    assert any(p.name == "Decision Lab" and p.price_inr == 4999 for p in account.products)
    assert "https://instagram.com/alpha" in account.external_links
    assert len(account.raw["pages_collected"]) == 2
    assert account.raw["pages_collected"][0]["content_sha256"] == "abc"


def test_discovery_query_budget_is_enforced(monkeypatch):
    from app.engine.discovery import expander

    calls = []

    async def fake_search(query, limit=8):
        calls.append(query)
        return [SearchHit(query=query, title="Alpha One", url="https://example.com/alpha",
                          provider="test", providers=["test"], rank=1)]

    monkeypatch.setattr(expander, "search", fake_search)
    monkeypatch.setattr(expander.settings, "discovery_query_budget", 3)
    asyncio.run(expander.expand("instagram", "alpha", "https://instagram.com/alpha/",
                                display_name="Alpha One"))
    assert len(calls) == 3


def test_html_report_exposes_identity_and_claim_ledgers():
    from app.engine import pipeline
    from app.engine.render import html
    from tests import fixtures

    report = pipeline.analyse(fixtures.chanchal_singh(), "verification-report")
    rendered = html.render(report)
    assert "Cross-source identity graph" in rendered
    assert "Verification ledger" in rendered
    assert "Search results discover candidates but do not prove ownership" in rendered


def test_multi_account_creator_ecosystem_keeps_primary_and_related_scopes_separate():
    """Regression for the live Demo Creator report that collapsed brand/clips into primary."""
    from app.engine import pipeline
    from app.engine.discovery.corroborate import enforce
    from app.engine.inference.signals import extract
    from app.engine.render import html

    seed = PlatformAccount(
        platform="instagram", handle="democreator",
        url="https://www.instagram.com/democreator/", display_name="Demo Creator",
        bio="Podcast host @figuringout.co", followers=9_600_000,
        raw={"verified_via": "seed"})
    raw = RawProfile(seed_url=seed.url, seed_platform="instagram",
                     seed_handle="democreator", display_name="Demo Creator")
    pipeline._add_account(raw, seed)
    pipeline._add_account(raw, PlatformAccount(
        platform="instagram", handle="democreator",
        url="https://instagram.com/democreator/?utm_source=test",
        display_name="Demo Creator", followers=9_600_000,
        raw={"verified_via": "probe"}))
    pipeline._add_account(raw, PlatformAccount(
        platform="instagram", handle="figuringout.co",
        url="https://instagram.com/figuringout.co/", display_name="Figuring Out",
        bio="Podcast host @democreator", followers=1_900_000,
        raw={"verified_via": "search+content"}))
    pipeline._add_account(raw, PlatformAccount(
        platform="youtube", handle="democreator", url="https://youtube.com/@democreator",
        display_name="Demo Creator", followers=18_500_000,
        raw={"verified_via": "probe"}))
    pipeline._add_account(raw, PlatformAccount(
        platform="youtube", handle="democreatorclips",
        url="https://youtube.com/@democreatorclips", display_name="Demo Creator Clips",
        bio="Official clips from Demo Creator", followers=1_610_000,
        raw={"verified_via": "search+content"}))
    pipeline._add_account(raw, PlatformAccount(
        platform="website", url="https://example-news.test/demo-creator-profile",
        display_name="Who is Demo Creator?", bio="Independent newspaper profile",
        products=[Product(name="After taking a loan", price_inr=10_000)],
        raw={"verified_via": "search+content"}))
    pipeline._add_account(raw, PlatformAccount(
        platform="linktree", url="https://linktr.ee/blog/example",
        display_name="Linktree Blog", raw={"verified_via": "owned_link"}))

    enforce(raw)
    assert sum(a.handle == "democreator" and a.platform == "instagram"
               for a in raw.accounts) == 1
    roles = {(a.platform, a.handle): a.raw.get("identity_role") for a in raw.accounts}
    assert roles[("instagram", "democreator")] == "primary"
    assert roles[("instagram", "figuringout.co")] == "associated_brand"
    assert roles[("youtube", "democreatorclips")] == "secondary_channel"
    assert not any(a.platform == "website" for a in raw.accounts)
    assert not any("/blog/" in a.url for a in raw.accounts)

    signals = extract(raw)
    assert signals.followers == {"instagram": 9_600_000, "youtube": 18_500_000}
    report = pipeline.analyse(raw, "multi-account-scope")
    instagram = [x for x in report.platform_matrix if x["platform"] == "instagram"]
    youtube = [x for x in report.platform_matrix if x["platform"] == "youtube"]
    assert [x["handle"] for x in instagram[:2]] == ["democreator", "figuringout.co"]
    assert [x["handle"] for x in youtube[:2]] == ["democreator", "democreatorclips"]
    rendered = html.render(report)
    assert "Primary creator account" in rendered
    assert "Associated brand/account" in rendered
    assert "Secondary/clips channel" in rendered
    assert "built-in method items" not in rendered


def test_visible_rupee_number_requires_commercial_context():
    from app.engine.collectors.web import _commercial_price_line
    assert not _commercial_price_line("After taking a ₹10,000 loan, the founder started a business")
    assert _commercial_price_line("Enroll in the workshop — fee ₹10,000")
