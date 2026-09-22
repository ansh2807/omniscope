"""Regression tests for the inference engine.

These assert *behaviour of the model*, not exact numbers — so a rule tweak that improves
things generally will not break the suite, but a change that inverts a conclusion will.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine import pipeline                       # noqa: E402
from app.engine.inference.signals import extract      # noqa: E402
from tests import fixtures                            # noqa: E402


def _model(name):
    raw = fixtures.ALL[name]()
    return extract(raw), pipeline.analyse(raw, f"test-{name}")


def test_archetype_classification():
    assert _model("sunil_panda")[0].archetype == "exam_prep_educator"
    assert _model("chanchal_singh")[0].archetype == "entrance_mentor"
    assert _model("rj_shubham")[0].archetype == "admissions_desk"
    assert _model("ishaan_arora")[0].archetype == "career_finance_creator"


def test_age_ordering_matches_life_stage():
    """Each creator's modal age must sit where their content forces it to sit."""
    ages = {n: max(_model(n)[1].audience.age.as_pct().items(), key=lambda kv: kv[1])[0]
            for n in fixtures.ALL}
    assert ages["sunil_panda"] in ("15-17", "18-20")
    assert ages["rj_shubham"] == "18-20"
    assert ages["ishaan_arora"] in ("18-20", "21-24")
    assert ages["chanchal_singh"] in ("21-24", "25-30")


def test_curriculum_lock_raises_confidence():
    """Curriculum-locked audiences must be modelled more confidently than broad ones."""
    locked = _model("sunil_panda")[1].audience.age.confidence
    broad = _model("ishaan_arora")[1].audience.age.confidence
    assert locked > broad, (locked, broad)


def test_geo_scope_detects_single_city():
    assert _model("rj_shubham")[0].geo_scope == "city"
    assert "Chandigarh" in _model("rj_shubham")[0].geo_terms


def test_price_ladder_does_not_invent_income():
    """Offer price is not evidence of the income of followers who did not buy it."""
    for name in fixtures.ALL:
        income = _model(name)[1].audience.income
        assert income.status.value == "unavailable"
        assert income.as_pct() == {}


def test_series_attrition_detected():
    sig = _model("sunil_panda")[0]
    assert sig.series_attrition is not None
    assert sig.series_attrition > 0.5, sig.series_attrition


def test_view_decay_callout_fires_for_sunil():
    kinds = {c["rule_id"] for c in _model("sunil_panda")[1].audience.callouts}
    assert "co.view_decay" in kinds


def test_dormant_seed_callout_fires_for_shubham():
    kinds = {c["rule_id"] for c in _model("rj_shubham")[1].audience.callouts}
    assert "co.dormant_seed" in kinds


def test_attention_efficiency_ordering():
    """RJ Shubham's small audience genuinely watches; Sunil's large one mostly does not."""
    rj = _model("rj_shubham")[0].sub_to_view
    sp = _model("sunil_panda")[0].sub_to_view
    assert rj > sp * 5, (rj, sp)


def test_language_detection():
    assert _model("chanchal_singh")[0].language == "english"


def test_every_distribution_sums_to_100():
    for name in fixtures.ALL:
        a = _model(name)[1].audience
        for dim in (a.age, a.gender, a.city_tier, a.income, a.device, a.format_mix, a.temperature):
            if dim.status.value == "unavailable":
                assert dim.as_pct() == {}, (name, dim.as_pct())
            else:
                assert sum(dim.as_pct().values()) == 100, (name, dim.as_pct())


def test_no_estimate_without_reasoning():
    for name in fixtures.ALL:
        a = _model(name)[1].audience
        for dim in (a.age, a.gender, a.city_tier, a.income, a.format_mix, a.temperature):
            assert dim.reasoning.strip(), name
        for est in filter(None, [a.top_cities, a.education, a.career_stage, a.language]):
            assert est.reasoning.strip(), (name, est.key)


def test_personas_and_activation_present():
    for name in fixtures.ALL:
        a = _model(name)[1].audience
        assert len(a.personas) >= 3, name
        assert len(a.activation) == 3, name
        assert a.unavailable, name


def test_renderers_produce_output(tmp_path=None):
    from app.engine.render import html as html_render
    from app.engine.render.docx_render import render as docx_render
    import tempfile, os
    raw = fixtures.chanchal_singh()
    payload = pipeline.analyse(raw, "render-test")
    out = html_render.render(payload)
    assert "<canvas id=\"cAge\"" in out and payload.subject_name in out
    d = tempfile.mkdtemp()
    p = docx_render(payload, os.path.join(d, "t.docx"))
    assert os.path.getsize(p) > 10_000


# --------------------------------------------------------------- v2 sections
def test_content_analysis_finds_real_patterns():
    """The engine must independently rediscover the formulas a human analyst found."""
    sunil = _model("sunil_panda")[1]
    phrases = {p.phrase for p in sunil.content.catalogue_patterns}
    assert any("one shot" in p for p in phrases), phrases

    ishaan = _model("ishaan_arora")[1]
    phrases = {p.phrase for p in ishaan.content.catalogue_patterns}
    assert any("finance course" in p for p in phrases), phrases


def test_promo_collapse_detected_for_shubham():
    c = _model("rj_shubham")[1].content
    assert c.promo_gap is not None and c.promo_gap > 0.5, c.promo_gap
    assert c.promo_median < c.organic_median


def test_series_attrition_surfaces_in_content():
    c = _model("sunil_panda")[1].content
    assert c.series and c.series[0]["attrition"] > 50


def test_age_normalisation_prevents_absurd_lift():
    """Age-adjusted lifts must stay in a defensible range even on a decaying channel."""
    c = _model("sunil_panda")[1].content
    for p in c.winning_patterns + c.losing_patterns:
        assert 0 < p.lift < 3, (p.phrase, p.lift)


def test_funnel_scores_chanchal_highest_on_proof():
    """41 public ratings are strong proof without being labelled paid transactions."""
    f = _model("chanchal_singh")[1].funnel
    proof = next(s for s in f.scores if s.dimension == "Social proof")
    assert proof.value >= 8, proof.value
    assert "not treated as paid transactions" in proof.why
    assert f.spread and f.spread > 20


def test_funnel_flags_missing_owned_audience():
    f = _model("rj_shubham")[1].funnel
    owned = next(s for s in f.scores if s.dimension == "Owned audience")
    assert owned.value <= 2


def test_sentiment_only_when_verbatim_exists():
    assert _model("chanchal_singh")[1].sentiment["verbatim_available"] is True
    assert _model("sunil_panda")[1].sentiment["verbatim_available"] is False


def test_sentiment_themes_are_evidence_backed():
    s = _model("chanchal_singh")[1].sentiment
    assert s["themes"], "expected themes from 4 verbatim reviews"
    for th in s["themes"]:
        assert th["quote"], th


def test_seo_degrades_honestly_without_search_provider():
    """Without a key, page-one ownership is unmeasurable — and the report must say so."""
    s = _model("sunil_panda")[1].seo
    assert s.assessed is False
    assert "need a results page" in s.reason_not_assessed
    assert s.grade in ("not assessed", "partial")


def test_all_thirteen_sections_present_in_payload():
    p = _model("chanchal_singh")[1]
    assert p.overview and p.content and p.funnel and p.seo
    assert p.platform_matrix and p.opportunities and p.recommendations
    assert p.desk and p.desk.get("needs")
    assert p.desk.get("kind") == "creator"
    assert p.sentiment and p.audience.personas and p.audience.unavailable


def test_platform_matrix_records_absences():
    rows = _model("chanchal_singh")[1].platform_matrix
    assert any(r["status"] == "not found" for r in rows)
    assert any(r["status"] == "found" for r in rows)


def test_cohort_orders_by_life_stage():
    import uuid
    payloads = [pipeline.analyse(fixtures.ALL[n](), uuid.uuid4().hex[:8]) for n in fixtures.ALL]
    cp = pipeline.analyse_cohort(payloads, "t")
    names = [l["name"] for l in cp.cohort.lifecycle]
    assert names.index("Sunil Panda") < names.index("Ishaan Arora")
    assert names.index("Ishaan Arora") < names.index("Chanchal Singh")


def test_cohort_overlap_abstains_without_shared_follower_data():
    import uuid
    payloads = [pipeline.analyse(fixtures.ALL[n](), uuid.uuid4().hex[:8]) for n in fixtures.ALL]
    cp = pipeline.analyse_cohort(payloads, "t")
    for o in cp.cohort.overlaps:
        assert o.low is None and o.high is None
        assert o.status == "unavailable" and o.confidence == 0
        assert 0 <= o.topic_similarity <= 100
    assert cp.cohort.sequential_pairs >= 1


def test_cohort_renders_both_formats():
    import os, tempfile, uuid
    from app.engine.render import html as html_render
    from app.engine.render.docx_render import render_cohort
    payloads = [pipeline.analyse(fixtures.ALL[n](), uuid.uuid4().hex[:8]) for n in fixtures.ALL]
    cp = pipeline.analyse_cohort(payloads, "t")
    out = html_render.render_cohort(cp)
    assert "Cohort Summary" in out and "cLife" in out
    d = tempfile.mkdtemp()
    p = render_cohort(cp, os.path.join(d, "c.docx"))
    assert os.path.getsize(p) > 40_000


def test_single_report_has_all_thirteen_html_sections():
    import re
    from app.engine.render import html as html_render
    out = html_render.render(_model("sunil_panda")[1])
    ids = re.findall(r'<section id="(\w+)"', out)
    for expected in ("exec", "overview", "platforms", "audience", "content", "sentiment",
                     "competitors", "seo", "funnel", "personas", "growth", "recs", "method"):
        assert expected in ids, (expected, ids)


# ------------------------------------------------------- v3: full-brief coverage
def test_personas_are_bounded_hypotheses_not_padding():
    for name in fixtures.ALL:
        personas = _model(name)[1].audience.personas
        assert len(personas) >= 3, (name, len(personas))
        names = [p.name for p in personas]
        assert len(set(names)) == len(names), f"duplicate personas for {name}"
        for p in personas:
            assert p.basis and 0 < p.confidence < 1
            for field in (p.goal, p.pain, p.watches, p.buys, p.also_on, p.reach_with):
                assert field.strip(), (name, p.name)


def test_private_demographic_taxonomy_abstains():
    for name in fixtures.ALL:
        a = _model(name)[1].audience
        for dim in (a.occupation, a.education_mix, a.career_mix,
                    a.sophistication, a.consumption):
            assert dim is None, name
        assert a.states
        assert a.english_proficiency and a.regional_language
        assert a.device.status.value == "unavailable" and not a.device.as_pct()
        assert a.english_proficiency.status.value == "unavailable"


def test_platform_analysis_covers_every_surface():
    for name in fixtures.ALL:
        p = _model(name)[1]
        assert len(p.platforms) == len(p.raw.accounts), name
        for pl in p.platforms:
            assert pl.follower_quality and pl.engagement_quality
            assert pl.community_strength and pl.virality
            assert pl.visual_style and pl.seo_note


def test_brand_analysis_scores_and_swot():
    for name in fixtures.ALL:
        br = _model(name)[1].brand
        assert br and len(br.pillars) == 5
        assert 0 <= br.total <= 50
        for quadrant in ("strengths", "weaknesses", "opportunities", "threats"):
            assert quadrant in br.swot, (name, quadrant)
        assert br.promise and br.proof and br.perception


def test_brand_scores_trust_from_countable_evidence():
    """Chanchal has 41 public ratings; Sunil has none. The evidence rubric reflects that."""
    ch = next(x for x in _model("chanchal_singh")[1].brand.pillars if x.name == "Trust")
    sp = next(x for x in _model("sunil_panda")[1].brand.pillars if x.name == "Trust")
    assert ch.score > sp.score, (ch.score, sp.score)


def test_growth_analysis_requires_exhaustive_history():
    g = _model("sunil_panda")[1].growth
    assert not g.measurable and "latest-plus-popular" in g.reason
    raw = fixtures.sunil_panda()
    for account in raw.accounts:
        if account.content:
            account.raw["content_is_exhaustive"] = True
    from app.engine.assemble import build
    exhaustive_only = build(raw, "exhaustive").growth
    assert not exhaustive_only.measurable
    assert "older uploads have had longer" in exhaustive_only.reason
    for item in raw.all_content():
        if item.views is not None and item.published_at:
            item.raw["views_metric_scope"] = "fixed_age"
            item.raw["views_age_days"] = 30
    measured = build(raw, "fixed-age").growth
    assert measured.measurable
    assert measured.trend in ("accelerating", "steady", "decelerating", "seasonal")


def test_comment_module_degrades_honestly_without_api_key():
    p = _model("chanchal_singh")[1]
    assert p.comments is not None
    assert p.comments.available is False
    assert "not read" in p.sentiment["scope_note"] or "login-walled" in p.sentiment["scope_note"]


def test_comment_analysis_on_synthetic_corpus():
    """Feed the analyser real-shaped comment text and check every category fires."""
    from app.engine.collectors.comments import Comment
    from app.engine.inference import comments as cmod
    raw = [
        Comment("Thank you so much sir, this cleared all my doubts", 120),
        Comment("Best teacher on youtube, respect", 90),
        Comment("What is the fees for this batch? kitna hai", 45),
        Comment("Sir please make a video on cash flow statement", 40),
        Comment("I am confused between CFA and FRM, which one is better?", 33),
        Comment("Still not able to understand, samajh nahi aaya", 20),
        Comment("Sir I got selected in SRCC because of you, thank you", 200),
        Comment("This was a waste of time, misleading title", 5),
        Comment("How to join the telegram group? link please", 18),
        Comment("When is the next batch starting?", 12),
    ] * 4
    ca = cmod.analyse(raw, notes=["synthetic"], creator_terms=["sunil", "panda"])
    assert ca.available and ca.sample_size == 40
    labels = {b.label for b in ca.buckets}
    for expected in ("Buying intent", "Confusion", "Content requests", "Outcome reports"):
        assert expected in labels, labels
    assert ca.sentiment["positive"] > ca.sentiment["negative"]
    assert ca.top_questions and ca.question_themes
    assert ca.vocabulary and ca.most_liked
    for b in ca.buckets:
        assert b.examples, b.label


def test_comment_analysis_never_invents_sentiment():
    from app.engine.inference import comments as cmod
    empty = cmod.analyse([], notes=[])
    assert empty.available is False
    assert empty.sentiment == {} and not empty.buckets


def test_competitor_comparison_fields_populated():
    """When competitors exist, the comparative columns must all be filled."""
    from app.engine.discovery.competitors import Competitor, CompetitorSet, _compare
    cs = CompetitorSet(assessed=True, subject_followers=70_000)
    cs.competitors = [
        Competitor(platform="instagram", handle="rival1",
                   url="https://instagram.com/rival1/", followers=500_000,
                   bio="Class 12 commerce accountancy teacher, board exam one shot"),
        Competitor(platform="instagram", handle="rival2",
                   url="https://instagram.com/rival2/", followers=9_000, bio="fitness coach"),
    ]
    _compare(cs, 70_000, ["board_exams", "commerce_subjects"])
    big, small = cs.competitors
    assert "larger" in big.size_vs_subject and "smaller" in small.size_vs_subject
    assert big.content_overlap > small.content_overlap
    for c in cs.competitors:
        assert c.audience_overlap and c.strength and c.weakness and c.positioning


def test_html_has_every_brief_section():
    import re
    from app.engine.render import html as html_render
    out = html_render.render(_model("sunil_panda")[1])
    ids = re.findall(r'<section id="(\w+)"', out)
    for expected in ("exec", "overview", "platforms", "audience", "content", "sentiment",
                     "competitors", "seo", "platforms2", "brand", "growth2", "funnel",
                     "personas", "growth", "recs", "method"):
        assert expected in ids, (expected, ids)


def test_html_renders_every_required_visualisation():
    import re
    from app.engine.render import html as html_render
    out = html_render.render(_model("sunil_panda")[1])
    canvases = set(re.findall(r'canvas id="(\w+)"', out))
    for expected in ("cAge", "cFmt", "cInt", "cTop", "cBrand", "cMatrix",
                     "cPlat", "cFun", "cPos"):
        assert expected in canvases, (expected, sorted(canvases))
    for fabricated in ("cInc", "cTier", "cDev", "cHeat", "cGrowth"):
        assert fabricated not in canvases


def test_every_distribution_still_sums_to_100_after_expansion():
    for name in fixtures.ALL:
        a = _model(name)[1].audience
        dims = [a.age, a.gender, a.city_tier, a.income, a.device, a.format_mix,
                a.temperature, a.occupation, a.education_mix, a.career_mix,
                a.sophistication, a.consumption]
        for d in [x for x in dims if x]:
            if d.status.value == "unavailable":
                assert d.as_pct() == {}
            else:
                assert sum(d.as_pct().values()) == 100, (name, d.as_pct())


# ------------------------------------------------------- browser tier parsers
def test_browser_parses_instagram_header_like_a_human_reads_it():
    """Exact text a logged-out Instagram profile renders, as captured by hand."""
    from app.engine.collectors import browser as br
    rendered = """chanchal_iim
33.3K followers
52 following
Chanchal Singh | MBA Mentor
IIM AHMEDABAD, MBA
Ace interview| CV | CAT
Consult 1:1
topmate.io/chanchal_singh
Self PrepforCAT
Resume
Info carousels
Workshops
Show more posts from chanchal_iim"""
    d = br.parse_instagram(rendered)
    assert d["followers"] == 33_300, d
    assert d["following"] == 52
    assert "Chanchal Singh" in (d.get("display_name") or "")
    assert any("topmate.io" in l for l in d["external_links"])
    assert "Resume" in d["highlights"]


def test_browser_parses_instagram_millions_and_verification():
    from app.engine.collectors import browser as br
    d = br.parse_instagram("ishaanarora1\n419K followers\n992 following\n"
                           "Ishaan Arora | Career & Education\nVerified\n")
    assert d["followers"] == 419_000 and d["following"] == 992
    assert d["verified"] is True


def test_browser_extracts_owned_website_embedded_inside_instagram_bio():
    from app.engine.collectors import browser as br
    d = br.parse_instagram(
        "democreator\n9.6M followers\nDemo Creator\nPodcast Host @figuringout.co "
        "www.figuringout.co/link/fo-544\nShow more posts from democreator")
    assert d["external_links"] == ["https://www.figuringout.co/link/fo-544"]


def test_browser_parses_youtube_both_sorts():
    """Rendered channel text, latest then the Popular sort — the click that matters."""
    from app.engine.collectors import browser as br
    rendered = """Sunil Panda-The Educator
@sunilpandaofficial
1.01M subscribers
4.5K videos
1:01:33
Nature & Significance of Management | ONE SHOT | Class 12th Business studies
2K views
18 hours ago
39:32
Admission of a Partner | Part 1 Basic, New & Sacrificing Ratio
2.4K views
1 day ago
===POPULAR===
24:22
INTRODUCTION TO ACCOUNTING | BASICS Part 1
1M views
5 years ago
25:36
Final Accounts | Part 1. Most Important For B.com
923K views
5 years ago"""
    d = br.parse_youtube(rendered)
    assert d["subscribers"] == 1_010_000, d["subscribers"]
    assert d["video_count"] == 4_500
    assert len(d["videos"]) == 2 and len(d["popular"]) == 2
    assert d["popular"][0]["views"] == 1_000_000
    assert d["videos"][0]["duration_seconds"] == 3693
    assert "ONE SHOT" in d["videos"][0]["title"]


def test_indian_localised_social_counts_are_not_truncated():
    """The live site renders lakh/crore on Indian machines, not just K/M/B."""
    from app.engine.numbers import parse_human_count
    from app.engine.collectors import browser as br

    assert parse_human_count("4.6 crore subscribers") == 46_000_000
    assert parse_human_count("8.5 lakh views") == 850_000
    assert parse_human_count("1.25 lac followers") == 125_000
    assert parse_human_count("1.5K videos") == 1_500

    rendered = """YouTube
@YouTube
4.6 crore subscribers
1.5K videos
7:08
Pabllo Vittar reacts to her Watch History
8.5 lakh views
6 days ago
0:31
The YouTube FIFA Creator Cup
17 lakh views
1 month ago"""
    parsed = br.parse_youtube(rendered)
    assert parsed["subscribers"] == 46_000_000
    assert parsed["video_count"] == 1_500
    assert [item["views"] for item in parsed["videos"]] == [850_000, 1_700_000]


def test_browser_parses_comment_threads():
    from app.engine.collectors import browser as br
    rendered = """===VIDEO https://youtu.be/abc123===
@student_raj
Thank you so much sir, this cleared all my doubts
2 days ago
120
@priya_m
What is the fees for this batch?
1 week ago
45
Reply
@anon
Sir please make a video on cash flow statement
3 days ago
12"""
    out = br.parse_comments(rendered)
    assert len(out) == 3, out
    assert out[0]["likes"] == 120
    assert "cleared all my doubts" in out[0]["text"]
    assert all(c["video_url"] == "https://youtu.be/abc123" for c in out)
    assert not any("ago" in c["text"] for c in out), "relative timestamps leaked into text"


def test_browser_tier_degrades_without_playwright():
    """Absent Playwright, every entry point must return cleanly with an install hint."""
    import asyncio
    from app.engine.collectors import browser as br
    if br.available():
        return
    for coro in (br.instagram_profile("x"), br.youtube_channel("x"),
                 br.youtube_comments(["https://youtu.be/x"])):
        r = asyncio.run(coro)
        assert r.ok is False and r.error and "playwright" in r.error.lower()


def test_platform_matrix_records_collection_tier():
    for name in fixtures.ALL:
        rows = _model(name)[1].platform_matrix
        found = [r for r in rows if r["status"] == "found"]
        assert found and all("tier" in r for r in found)


# ------------------------------------------------- enrichment must never block
def test_walled_post_grid_does_not_block_the_report():
    """A login-walled Instagram post grid is normal. It must not stop generation."""
    raw = fixtures.chanchal_singh()
    ig = next(a for a in raw.accounts if a.platform == "instagram")
    ig.needs_manual = True          # what a real collection sets
    assert ig.followers, "fixture should carry a follower count"
    blocked = [a for a in raw.accounts
               if a.platform == "instagram" and a.followers is None]
    assert not blocked, "a walled grid must not count as a blocking failure"
    p = pipeline.analyse(raw, "t")
    assert p.audience and p.content and p.funnel


def test_missing_follower_count_does_not_block_the_report():
    raw = fixtures.chanchal_singh()
    ig = next(a for a in raw.accounts if a.platform == "instagram")
    ig.followers = None
    p = pipeline.analyse(raw, "t")
    assert p.audience and p.content and p.funnel


# --------------------------------------------------- handle probing (no API key)
def test_handle_variants_are_sensible():
    from app.engine.discovery.probe import variants
    v = variants("sunilpandaofficial", "Sunil Panda")
    assert "sunilpandaofficial" in v
    assert "sunilpanda" in v, v
    assert not any(x.endswith("officialofficial") for x in v), v
    v2 = variants("demo.creator", "Demo Creator")
    assert "democreator" in v2 and "demo_creator" in v2


def test_probe_identity_matching_rejects_wrong_person():
    from app.engine.discovery.probe import _matches, _tokens
    toks = _tokens("Sunil Panda", "sunilpandaofficial")
    ok, conf, _ = _matches("Sunil Panda - The Educator, commerce classes",
                           "Sunil Panda", "sunilpandaofficial", toks)
    assert ok and conf >= 0.6
    bad, conf2, why = _matches("Cooking with Maria - recipes and food",
                               "Maria's Kitchen", "sunilpandaofficial", toks)
    assert not bad and conf2 == 0.0
    assert "does not identify" in why


# -------------------------------------------- rounded follower counts are flagged
def test_rounded_meta_follower_counts_are_flagged():
    from app.engine.collectors.instagram import _suspicious
    # One significant figure on a large number: 10M could be 9.5M-10.5M.
    assert _suspicious(10_000_000, "10M") is True
    assert _suspicious(2_000_000, "2M") is True
    assert _suspicious(500_000, "500K") is True
    # Real readings carry more information and are trusted.
    assert _suspicious(1_700_000, "1.7M") is False
    assert _suspicious(1_743_208, "1,743,208") is False
    assert _suspicious(33_300, "33.3K") is False
    assert _suspicious(1_919, "1,919") is False


# ----------------------------------------------------------- storage hygiene
def test_housekeeping_prunes_and_reports(tmp_path=None):
    import tempfile, time
    from pathlib import Path as _P
    from sqlmodel import Session, SQLModel, create_engine
    from app.config import settings as _s
    from app.models import Report

    d = _P(tempfile.mkdtemp())
    (d / "reports").mkdir()
    (d / "cache").mkdir()
    old_reports, old_cache = _s.reports_dir, _s.cache_dir
    old_max, old_ret, old_ttl = _s.max_reports, _s.retention_days, _s.report_ttl_minutes
    _s.reports_dir, _s.cache_dir = str(d / "reports"), str(d / "cache")
    _s.max_reports, _s.retention_days, _s.report_ttl_minutes = 2, 0, 0
    try:
        eng = create_engine(f"sqlite:///{d/'t.db'}")
        SQLModel.metadata.create_all(eng)
        from datetime import datetime, timedelta
        with Session(eng) as db:
            for i in range(5):
                f = d / "reports" / f"r{i}.html"
                f.write_text("x" * 1000)
                db.add(Report(id=f"r{i}", job_id="j", share_slug=f"s{i}",
                              subject_name="n", subject_handle="@n", seed_url="u",
                              html_path=str(f),
                              created_at=datetime.utcnow() - timedelta(hours=i)))
            db.commit()
        for i in range(3):
            (d / "cache" / f"c{i}.json").write_text("{}")

        from tools import housekeeping
        swept = housekeeping.sweep(eng)
        assert swept.reports_deleted == 3, swept
        assert swept.reports_kept == 2
        assert swept.bytes_freed > 0
        assert len(list((d / "reports").glob("*.html"))) == 2
    finally:
        _s.reports_dir, _s.cache_dir = old_reports, old_cache
        _s.max_reports, _s.retention_days, _s.report_ttl_minutes = old_max, old_ret, old_ttl


def test_housekeeping_never_deletes_inside_retention():
    import tempfile
    from datetime import datetime
    from pathlib import Path as _P
    from sqlmodel import Session, SQLModel, create_engine
    from app.config import settings as _s
    from app.models import Report

    d = _P(tempfile.mkdtemp())
    (d / "reports").mkdir(); (d / "cache").mkdir()
    old = (_s.reports_dir, _s.cache_dir, _s.max_reports, _s.retention_days,
           _s.report_ttl_minutes)
    _s.reports_dir, _s.cache_dir = str(d / "reports"), str(d / "cache")
    _s.max_reports, _s.retention_days, _s.report_ttl_minutes = 0, 30, 0
    try:
        eng = create_engine(f"sqlite:///{d/'t.db'}")
        SQLModel.metadata.create_all(eng)
        with Session(eng) as db:
            f = d / "reports" / "fresh.html"
            f.write_text("x")
            db.add(Report(id="fresh", job_id="j", share_slug="s", subject_name="n",
                          subject_handle="@n", seed_url="u", html_path=str(f),
                          created_at=datetime.utcnow()))
            db.commit()
        from tools import housekeeping
        swept = housekeeping.sweep(eng)
        assert swept.reports_deleted == 0
        assert (d / "reports" / "fresh.html").exists()
    finally:
        (_s.reports_dir, _s.cache_dir, _s.max_reports, _s.retention_days,
         _s.report_ttl_minutes) = old


def test_diagnostics_structure_is_actionable():
    """Every failing check must carry a fix; passing ones must carry detail."""
    import asyncio
    from tools import diagnostics
    rep = asyncio.run(diagnostics.run())
    assert rep.checks and rep.verdict
    names = [c.name for c in rep.checks]
    for expected in ("Internet access", "Browser engine installed", "YouTube collection",
                     "Search / discovery", "Comment collection"):
        assert expected in names, names
    for c in rep.checks:
        assert c.detail, f"{c.name} reported nothing"
        if not c.ok:
            assert c.fix, f"{c.name} failed without telling the user how to fix it"


# ------------------------------------------------- keyless discovery (no API key)
def test_keyless_podcast_filter_rejects_unrelated_shows():
    """A name search returns plenty of noise. Only real mentions may be kept."""
    import json as _json
    from app.engine.discovery import keyless

    payload = {"results": [
        {"trackName": "Figuring Out with Demo Creator", "trackViewUrl": "https://a",
         "artistName": "Demo Creator", "description": "Demo Creator interviews founders"},
        {"trackName": "The Daily Gardening Show", "trackViewUrl": "https://b",
         "artistName": "Someone Else", "description": "All about roses and compost"},
    ]}

    class FakeResp:
        ok, text = True, _json.dumps(payload)

    async def fake_fetch(url, **kw):
        return FakeResp()

    import asyncio
    orig = keyless.fetch
    keyless.fetch = fake_fetch
    try:
        hits = asyncio.run(keyless.podcasts("Demo Creator"))
    finally:
        keyless.fetch = orig
    titles = [h.title for h in hits]
    assert any("Figuring Out" in t for t in titles), titles
    assert not any("Gardening" in t for t in titles), titles


def test_keyless_autocomplete_buckets_intent():
    import asyncio
    import json as _json
    from app.engine.discovery import keyless

    suggestions = ["sunil panda fees", "sunil panda course", "sunil panda review",
                   "sunil panda worth it", "sunil panda notes pdf", "sunil panda telegram",
                   "sunil panda age", "sunil panda contact number"]

    class FakeResp:
        ok = True
        text = _json.dumps(["seed", suggestions])

    async def fake_fetch(url, **kw):
        return FakeResp()

    orig = keyless.fetch
    keyless.fetch = fake_fetch
    try:
        out = asyncio.run(keyless.related_searches("sunil panda"))
    finally:
        keyless.fetch = orig
    labels = {i["intent"] for i in out["intents"]}
    for expected in ("Price and access", "Commercial investigation",
                     "Identity and background", "Contact and support",
                     "Content and resources"):
        assert expected in labels, labels
    for i in out["intents"]:
        assert i["examples"], i


def test_keyless_wikipedia_requires_a_name_match():
    """A search hit whose title shares no token with the subject must be rejected."""
    import asyncio
    import json as _json
    from app.engine.discovery import keyless

    class FakeResp:
        ok = True
        text = _json.dumps({"query": {"search": [{"title": "Completely Different Person"}]}})

    async def fake_fetch(url, **kw):
        return FakeResp()

    orig = keyless.fetch
    keyless.fetch = fake_fetch
    try:
        out = asyncio.run(keyless.wikipedia("Sunil Panda"))
    finally:
        keyless.fetch = orig
    assert out["title"] is None, out


def test_seo_uses_keyless_related_searches_without_a_key():
    from app.engine.inference import seo as seo_mod
    from app.engine.inference.signals import extract
    raw = fixtures.sunil_panda()
    raw.keyless = {
        "related_searches": ["sunil panda fees", "sunil panda notes pdf",
                             "sunil panda worth it"],
        "autocomplete_intents": [{"intent": "Price and access", "count": 1, "share": 33,
                                  "examples": ["sunil panda fees"]}],
    }
    s = seo_mod.assess(raw, extract(raw))
    assert s.related_searches and s.autocomplete_intents
    assert s.grade == "partial"
    assert "keylessly" in s.reason_not_assessed


# ------------------------------------------- verification gate (false positives)
def test_gate_rejects_stranger_linkedin():
    """The exact failure seen in production: a random person's LinkedIn attributed."""
    from app.engine.discovery import verify as v
    verdict = v.check(
        platform="linkedin",
        url="https://www.linkedin.com/in/navya-srivastava-46453b247",
        from_owned_link=False, probe_confirmed=False, probe_confidence=0.0,
        subject_handle="democreator", subject_name="Demo Creator")
    assert verdict.accept is False
    assert "authentication wall" in verdict.reason


def test_gate_rejects_bare_domains():
    from app.engine.discovery import verify as v
    for platform, url in [("playstore", "https://play.google.com"),
                          ("podcast", "https://podcasts.apple.com"),
                          ("instagram", "https://www.instagram.com/")]:
        assert not v.is_real_profile_url(platform, url), (platform, url)
    assert v.is_real_profile_url(
        "playstore", "https://play.google.com/store/apps/details?id=com.example")
    assert v.is_real_profile_url("podcast", "https://podcasts.apple.com/in/podcast/id123456789")


def test_gate_rejects_implausibly_small_accounts():
    """A 3-member channel does not belong to a creator with millions elsewhere."""
    from app.engine.discovery import verify as v
    verdict = v.check(platform="telegram", url="https://t.me/s/democreator",
                      from_owned_link=False, probe_confirmed=True, probe_confidence=0.9,
                      followers=3, items=0, primary_followers=9_600_000,
                      subject_handle="democreator")
    assert verdict.accept is False
    assert "different person" in verdict.reason


def test_gate_accepts_owned_links_without_further_proof():
    from app.engine.discovery import verify as v
    verdict = v.check(platform="telegram", url="https://t.me/s/somechannel",
                      from_owned_link=True, probe_confirmed=False, probe_confidence=0.0,
                      subject_handle="x")
    assert verdict.accept and verdict.source == "owned_link"


def test_gate_allows_small_secondary_for_small_subject():
    """The scale check must not fire when the subject is itself small."""
    from app.engine.discovery import verify as v
    verdict = v.check(platform="telegram", url="https://t.me/s/tinychannel",
                      from_owned_link=False, probe_confirmed=True, probe_confidence=0.8,
                      followers=12, items=0, primary_followers=1_900,
                      subject_handle="tinychannel")
    assert verdict.accept is True


def test_rejected_candidates_appear_in_the_report():
    raw = fixtures.chanchal_singh()
    raw.rejected = [{"platform": "linkedin",
                     "url": "https://www.linkedin.com/in/someone-else",
                     "reason": "Rejected: linkedin is behind an authentication wall."}]
    p = pipeline.analyse(raw, "t")
    row = next(r for r in p.platform_matrix if r["platform"] == "linkedin")
    assert row["status"] == "rejected"
    from app.engine.render import html as html_render
    out = html_render.render(p)
    assert "considered and rejected" in out


def test_youtube_probe_rejects_squatted_handles():
    """A handle match on an empty channel is not the creator's channel."""
    import asyncio
    from app.engine.discovery import probe as pr

    class FakeResp:
        ok = True
        # handle matches, but zero videos and a single subscriber
        text = ('<title>democreator - YouTube</title>'
                '"subscriberCountText":{"simpleText":"1 subscriber"}')

    async def fake_fetch(url, **kw):
        return FakeResp()

    orig = pr.fetch
    pr.fetch = fake_fetch
    try:
        hit = asyncio.run(pr._youtube("democreator", pr._tokens("Demo Creator")))
    finally:
        pr.fetch = orig
    assert hit is not None
    assert hit.confirmed is False, hit.evidence
    assert "squatted" in hit.evidence or "abandoned" in hit.evidence


# ============================================================ commercial layer
def _commercial_db():
    import tempfile
    from pathlib import Path as _P
    from sqlmodel import SQLModel, create_engine
    from app.commercial import models as cm  # noqa: F401
    from app.commercial.plans import seed
    d = _P(tempfile.mkdtemp())
    eng = create_engine(f"sqlite:///{d/'c.db'}")
    SQLModel.metadata.create_all(eng)
    seed(eng)
    return eng


def test_license_key_format_is_transcribable():
    from app.commercial.models import new_license_key
    for _ in range(50):
        k = new_license_key()
        assert k.startswith("CI-") and len(k) == 22, k
        body = k[3:].replace("-", "")
        # No characters that get misread down a phone line.
        assert not (set(body) & set("O0I1L")), k


def test_trial_org_is_allowed_then_blocked_on_quota():
    from sqlmodel import Session
    from app.commercial import entitlements as ent_lib
    from app.commercial.models import Org, OrgStatus, trial_expiry
    eng = _commercial_db()
    with Session(eng) as db:
        org = Org(name="T", email="t@x.com", status=OrgStatus.TRIAL.value,
                  plan_code="trial", trial_ends_at=trial_expiry(7))
        db.add(org); db.commit(); db.refresh(org)

        ent = ent_lib.resolve(db, org)
        assert ent.allowed and ent.reports_limit == 3

        for _ in range(3):
            ent_lib.consume(db, org)
        ent = ent_lib.resolve(db, org)
        assert not ent.allowed
        assert "used all 3 reports" in ent.reason
        assert ent.upgrade_hint == "quota_exceeded"


def test_expired_trial_is_blocked():
    from datetime import datetime, timedelta
    from sqlmodel import Session
    from app.commercial import entitlements as ent_lib
    from app.commercial.models import Org, OrgStatus
    eng = _commercial_db()
    with Session(eng) as db:
        org = Org(name="T", email="e@x.com", status=OrgStatus.TRIAL.value,
                  plan_code="trial",
                  trial_ends_at=datetime.utcnow() - timedelta(days=1))
        db.add(org); db.commit(); db.refresh(org)
        ent = ent_lib.resolve(db, org)
        assert not ent.allowed and ent.upgrade_hint == "trial_expired"


def test_manual_override_beats_everything():
    from datetime import datetime, timedelta
    from sqlmodel import Session
    from app.commercial import entitlements as ent_lib
    from app.commercial.models import Org, OrgStatus
    eng = _commercial_db()
    with Session(eng) as db:
        org = Org(name="P", email="p@x.com", status=OrgStatus.SUSPENDED.value,
                  plan_code="trial",
                  override_until=datetime.utcnow() + timedelta(days=30),
                  override_reason="pilot")
        db.add(org); db.commit(); db.refresh(org)
        ent = ent_lib.resolve(db, org)
        assert ent.allowed and "Manual override" in ent.reason


def test_suspended_and_cancelled_are_blocked_with_distinct_reasons():
    from sqlmodel import Session
    from app.commercial import entitlements as ent_lib
    from app.commercial.models import Org, OrgStatus
    eng = _commercial_db()
    with Session(eng) as db:
        for status, marker in ((OrgStatus.SUSPENDED.value, "suspended"),
                               (OrgStatus.CANCELLED.value, "cancelled")):
            org = Org(name=status, email=f"{status}@x.com", status=status,
                      plan_code="agency")
            db.add(org); db.commit(); db.refresh(org)
            ent = ent_lib.resolve(db, org)
            assert not ent.allowed and marker in ent.reason.lower()


def test_unlimited_plan_never_exhausts():
    from sqlmodel import Session
    from app.commercial import entitlements as ent_lib
    from app.commercial.models import Org, OrgStatus
    eng = _commercial_db()
    with Session(eng) as db:
        org = Org(name="S", email="s@x.com", status=OrgStatus.ACTIVE.value,
                  plan_code="selfhost")
        db.add(org); db.commit(); db.refresh(org)
        for _ in range(50):
            ent_lib.consume(db, org)
        ent = ent_lib.resolve(db, org)
        assert ent.allowed and ent.unlimited and ent.reports_left is None


def test_revoked_key_is_rejected():
    from datetime import datetime
    from sqlmodel import Session
    from app.commercial import entitlements as ent_lib
    from app.commercial.models import LicenseKey, Org
    eng = _commercial_db()
    with Session(eng) as db:
        org = Org(name="R", email="r@x.com")
        db.add(org); db.commit(); db.refresh(org)
        key = LicenseKey(org_id=org.id, active=False,
                         revoked_at=datetime.utcnow(), revoke_reason="chargeback")
        db.add(key); db.commit()
        found, row, err = ent_lib.org_for_key(db, key.key)
        assert found is None and "revoked" in err and "chargeback" in err


def test_webhook_signature_verification():
    import hashlib, hmac
    from app.commercial import razorpay_client as rz
    from app.config import settings as s
    old = s.razorpay_webhook_secret
    s.razorpay_webhook_secret = "testsecret"
    try:
        body = b'{"event":"subscription.charged"}'
        good = hmac.new(b"testsecret", body, hashlib.sha256).hexdigest()
        assert rz.verify_webhook(body, good) is True
        assert rz.verify_webhook(body, "deadbeef") is False
        assert rz.verify_webhook(b'{"event":"tampered"}', good) is False
        assert rz.verify_webhook(body, "") is False
    finally:
        s.razorpay_webhook_secret = old


def test_webhook_event_mapping_covers_lifecycle():
    from app.commercial import razorpay_client as rz
    for event, expected in [("subscription.activated", "active"),
                            ("subscription.halted", "past_due"),
                            ("subscription.cancelled", "cancelled"),
                            ("payment.failed", "past_due")]:
        assert rz.EVENT_MAP[event] == expected


def test_webhook_interpret_extracts_org_and_period():
    from app.commercial import razorpay_client as rz
    payload = {"event": "subscription.charged", "payload": {"subscription": {"entity": {
        "id": "sub_123", "status": "active", "customer_id": "cust_1",
        "current_start": 1767225600, "current_end": 1769904000,
        "notes": {"org_id": "org_abc", "plan_code": "agency"}}}}}
    out = rz.interpret("subscription.charged", payload)
    assert out["org_id"] == "org_abc" and out["subscription_id"] == "sub_123"
    assert out["org_status"] == "active" and out["current_end"] is not None


def test_updater_rejects_bad_checksum():
    """A download whose hash does not match the published value must be discarded."""
    import tempfile, zipfile
    from pathlib import Path as _P
    from tools import updater
    d = _P(tempfile.mkdtemp())
    (d / "data").mkdir()
    z = d / "fake.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("app/x.py", "print('x')")
    old_root, old_backups = updater.ROOT, updater.BACKUPS
    updater.ROOT, updater.BACKUPS = d, d / "data" / "backups"
    try:
        out = updater.apply_update(
            {"version": "99.0.0", "download_url": z.as_uri(), "sha256": "0" * 64},
            "2.1.0", allow_major=True)
        assert "Checksum mismatch" in out, out
        assert not (d / "data" / "update-99.0.0.zip").exists(), "bad download not cleaned up"
    finally:
        updater.ROOT, updater.BACKUPS = old_root, old_backups


def test_updater_applies_a_verified_release():
    """A correctly-hashed release unpacks, backs up, and never touches .env or data/."""
    import hashlib, tempfile, zipfile
    from pathlib import Path as _P
    from tools import updater
    d = _P(tempfile.mkdtemp())
    (d / "data").mkdir()
    (d / "app").mkdir()
    (d / "app" / "old.py").write_text("old")
    (d / ".env").write_text("SECRET=keepme")
    (d / "data" / "mine.db").write_text("customer data")

    z = d / "rel.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("creator-intel/app/new.py", "print('new')")
        zf.writestr("creator-intel/.env", "SECRET=OVERWRITTEN")
        zf.writestr("creator-intel/data/mine.db", "OVERWRITTEN")
    digest = hashlib.sha256(z.read_bytes()).hexdigest()

    old_root, old_backups = updater.ROOT, updater.BACKUPS
    updater.ROOT, updater.BACKUPS = d, d / "data" / "backups"
    try:
        out = updater.apply_update(
            {"version": "2.2.0", "download_url": z.as_uri(), "sha256": digest}, "2.1.0")
        assert "Updated to 2.2.0" in out, out
        assert (d / "app" / "new.py").exists()
        # local config and customer data must survive an update
        assert (d / ".env").read_text() == "SECRET=keepme"
        assert (d / "data" / "mine.db").read_text() == "customer data"
    finally:
        updater.ROOT, updater.BACKUPS = old_root, old_backups


def test_updater_refuses_major_upgrade_by_default():
    from tools import updater
    out = updater.apply_update({"version": "3.0.0", "download_url": "http://x/y.zip"},
                               "2.1.0")
    assert "major upgrade" in out


def test_updater_offline_grace_uses_cached_entitlement():
    import json as _json, tempfile
    from datetime import datetime, timedelta
    from pathlib import Path as _P
    from tools import updater
    d = _P(tempfile.mkdtemp())
    old_state = updater.STATE
    updater.STATE = d / "state.json"
    try:
        updater.STATE.write_text(_json.dumps({
            "last_good": {"valid": True, "reason": "ok", "grace_days": 14,
                          "plan": {"name": "Agency"}, "usage": {}},
            "last_check": (datetime.utcnow() - timedelta(days=3)).isoformat(),
        }))
        st = updater.check_license("http://127.0.0.1:1", "CI-XXXX", "2.1.0", timeout=1)
        assert st.valid is True and st.offline is True
        assert "cached" in st.reason

        updater.STATE.write_text(_json.dumps({
            "last_good": {"valid": True, "grace_days": 14, "plan": {}, "usage": {}},
            "last_check": (datetime.utcnow() - timedelta(days=40)).isoformat(),
        }))
        st2 = updater.check_license("http://127.0.0.1:1", "CI-XXXX", "2.1.0", timeout=1)
        assert st2.valid is False
    finally:
        updater.STATE = old_state


def test_plans_seed_is_idempotent():
    from sqlmodel import Session, select
    from app.commercial.models import Plan
    from app.commercial.plans import seed
    eng = _commercial_db()
    added = seed(eng)          # already seeded by the helper
    assert added == 0
    with Session(eng) as db:
        codes = {p.code for p in db.exec(select(Plan)).all()}
    assert {"trial", "solo", "agency", "selfhost"} <= codes
