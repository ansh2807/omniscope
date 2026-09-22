"""Diverse-profile calibration prevents same-report and leakage regressions."""
from app.engine import calibration, pipeline
from tests import fixtures


def _reports():
    return [pipeline.analyse(factory(), factory.__name__) for factory in (
        fixtures.sunil_panda, fixtures.chanchal_singh,
        fixtures.rj_shubham, fixtures.ishaan_arora)]


def test_diverse_creator_corpus_passes_accuracy_calibration():
    result = calibration.evaluate(_reports())
    assert result.passed, result.as_dict()
    assert len(set(result.output_fingerprints.values())) == 4
    assert max(x["similarity"] for x in result.recommendation_similarity) <= 0.72


def test_calibration_detects_copied_recommendations():
    reports = _reports()[:2]
    reports[1].recommendations = list(reports[0].recommendations)
    result = calibration.evaluate(reports)
    assert not result.passed
    assert any(x.code == "recommendation_copy_risk" for x in result.issues)


def test_calibration_detects_private_metric_overclaim():
    reports = _reports()[:1]
    reports[0].audience.gender.status = "modelled"
    result = calibration.evaluate(reports)
    assert not result.passed
    assert any(x.code == "private_metric_overclaim" for x in result.issues)


def test_topic_matching_never_reads_cat_inside_watercolour():
    from app.engine.inference.signals import _term_hits
    assert _term_hits("watercolour portrait tutorial", "cat") == 0
    assert _term_hits("CAT exam percentile", "cat exam") == 1
    assert _term_hits("training programme", "ai") == 0


def test_out_of_domain_profile_abstains_from_age_and_personas():
    from app.schemas import ContentItem, PlatformAccount, RawProfile
    account = PlatformAccount(
        platform="youtube", handle="paintlab", url="https://youtube.com/@paintlab",
        display_name="Paint Lab", followers=1000, raw={"verified_via": "seed"},
        content=[ContentItem(platform="youtube", title="Watercolour portrait tutorial"),
                 ContentItem(platform="youtube", title="Mixing skin tones")])
    raw = RawProfile(seed_url=account.url, seed_platform="youtube", seed_handle="paintlab",
                     display_name="Paint Lab", accounts=[account])
    report = pipeline.analyse(raw, "paint-lab")
    assert report.audience.archetype == "generalist_creator"
    assert report.audience.age.status.value == "unavailable"
    assert report.audience.personas == []
