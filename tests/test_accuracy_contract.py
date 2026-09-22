"""Regression tests for claims that used to look precise but were not evidence-backed."""
from datetime import datetime, timedelta

from app.engine.assemble import build
from app.engine.cohort import analyse as analyse_cohort
from app.engine.collectors.instagram import merge_manual
from app.engine.inference.content import analyse as analyse_content
from app.schemas import ContentItem
from tests import fixtures


def test_video_topics_never_become_creator_credentials():
    report = build(fixtures.ishaan_arora(), "ishaan")
    expertise = next(p for p in report.brand.pillars if p.name == "Expertise")
    joined = " ".join(expertise.evidence + report.brand.proof).lower()
    for false_credential in ("cfa charter", "frm charter", "chartered accountant",
                             "acca credential", "cpa credential", "sebi registration",
                             "big 4 experience"):
        assert false_credential not in joined


def test_rating_count_is_not_relabelled_as_transactions_or_written_reviews():
    report = build(fixtures.chanchal_singh(), "chanchal")
    proof = report.funnel.social_proof
    assert proof["ratings"] == 41
    assert proof["testimonials"] == 4
    corpus = " ".join(s.why for s in report.funnel.scores).lower()
    assert "41 completed" not in corpus
    assert "41 public ratings" in corpus
    assert "4 collected written review texts" in corpus


def test_private_demographics_are_unavailable_without_insights():
    report = build(fixtures.sunil_panda(), "sunil")
    for field in (report.audience.gender, report.audience.city_tier,
                  report.audience.income, report.audience.device,
                  report.audience.temperature):
        assert field.status.value == "unavailable"
        assert field.as_pct() == {}
    assert report.audience.top_cities.status.value == "unavailable"
    assert report.audience.top_cities.value == []


def test_manual_first_party_demographics_override_abstention_exactly():
    raw = fixtures.sunil_panda()
    instagram = raw.account("instagram")
    merge_manual(instagram, {
        "audience_age": "18-24:41, 25-34:33, 35-44:26",
        "audience_gender": "male:68, female:32",
        "audience_cities": "Delhi, Mumbai, Bengaluru",
    })
    report = build(raw, "manual")
    assert report.audience.age.status.value == "observed"
    assert report.audience.age.as_pct() == {"18-24": 41, "25-34": 33, "35-44": 26}
    assert report.audience.gender.status.value == "observed"
    assert report.audience.gender.as_pct() == {"male": 68, "female": 32}
    assert report.audience.top_cities.status.value == "observed"
    assert report.audience.top_cities.value == ["Delhi", "Mumbai", "Bengaluru"]


def test_current_median_uses_latest_sample_and_never_popular_rows():
    now = datetime(2026, 8, 5)
    latest = [ContentItem(platform="youtube", title=f"Latest {i}", views=v,
                          published_at=now - timedelta(days=i),
                          raw={"sample": ["latest"]})
              for i, v in enumerate((100, 200, 300, 400, 500, 600))]
    popular = [ContentItem(platform="youtube", title=f"Popular {i}", views=v,
                           published_at=now - timedelta(days=1000 + i),
                           raw={"sample": ["popular"]})
               for i, v in enumerate((1_000_000, 2_000_000, 3_000_000, 4_000_000))]
    result = analyse_content(latest + popular, subscribers=10_000, now=now)
    assert result.current_median == 350
    assert result.current_sample == 6
    assert result.catalogue_median is None
    assert result.decay_ratio is None


def test_decay_ratio_means_recent_over_older_not_recent_over_top():
    result = build(fixtures.sunil_panda(), "sunil").content
    assert result.decay_ratio == round(result.current_median / result.catalogue_median, 4)
    assert result.decay_ratio != round(result.current_median / result.top_views, 4)


def test_undated_mixed_sample_has_no_fake_current_window():
    rows = [ContentItem(platform="youtube", title=f"Video {i}", views=i * 100)
            for i in range(1, 9)]
    result = analyse_content(rows, subscribers=1000)
    assert result.current_median is None
    assert result.catalogue_median is None
    assert result.decay_ratio is None


def test_following_ratio_does_not_claim_audience_authenticity():
    report = build(fixtures.sunil_panda(), "sunil")
    instagram = next(p for p in report.platforms if p.platform == "instagram")
    assert instagram.follower_quality == "not measurable"
    assert "cannot distinguish" in instagram.follower_note


def test_search_volume_is_never_invented_from_content_topics():
    report = build(fixtures.ishaan_arora(), "ishaan")
    assert report.seo.intent_clusters
    assert all(c["value"] == "Search volume and ranking not measured"
               for c in report.seo.intent_clusters)


def test_sparse_sample_never_claims_seasonality_or_growth():
    report = build(fixtures.ishaan_arora(), "ishaan")
    assert not report.content.seasonality_measured
    assert report.audience.seasonality == {}
    assert not report.growth.measurable


def test_cohort_overlap_is_unavailable_without_shared_ids():
    reports = [build(fn(), key) for key, fn in fixtures.ALL.items()]
    cohort = analyse_cohort(reports)
    assert not cohort.overlap_measurable
    assert cohort.overlaps
    assert all(o.low is None and o.high is None and o.confidence == 0
               for o in cohort.overlaps)


def test_summed_following_is_not_described_as_unique_audience():
    report = build(fixtures.sunil_panda(), "sunil")
    stat = report.headline_stats[0]
    assert stat["label"] == "Summed public following"
    assert "duplicates unknown" in stat["note"]


def test_callouts_never_turn_count_associations_into_audience_behaviour():
    report = build(fixtures.sunil_panda(), "sunil")
    text = " ".join(f"{x['title']} {x['body']}" for x in report.audience.callouts).lower()
    for unsupported in ("audience increasingly lives", "consistently prefer",
                        "high-return change", "lose most of their audience"):
        assert unsupported not in text
    assert "summed public follows" in text
    assert "does not measure the same viewers" in text


def test_brand_map_uses_explicit_evidence_indices_not_follower_niche_assumptions():
    report = build(fixtures.chanchal_singh(), "chanchal")
    note = report.brand.position_note.lower()
    assert "public-scale index" in note
    assert "commercial-infrastructure index" in note
    assert "buyer" in note and "conversion" in note
    assert "internal public-evidence rubric" in report.brand.perception.lower()


def test_deep_report_exposes_formulas_and_decision_gates():
    from app.engine.render.html import render
    html = render(build(fixtures.sunil_panda(), "sunil"))
    for required in ("Research confidence and decision risk", "Formula glossary",
                     "View Gini", "Publishing burstiness",
                     "Decision-gate validation register"):
        assert required in html
    assert "Conversion, revenue and retention" in html
