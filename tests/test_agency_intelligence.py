from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.engine.inference.agency_intelligence import (
    analyse_agency_intelligence,
    rank_lookalike_creators,
)
from app.schemas import (
    ClaimStatus,
    ContentItem,
    Distribution,
    PlatformAccount,
    RawProfile,
)


NOW = datetime(2026, 8, 6)


def _item(index: int, *, views: int = 10_000, brand: str | None = None) -> ContentItem:
    raw = {"sample": ["latest"], "views_age_days": 30}
    if brand:
        raw.update({"paid_partnership": True, "brand": brand})
    return ContentItem(
        platform="youtube", title=f"Evidence item {index}",
        url=f"https://youtube.com/watch?v=evidence{index}", views=views,
        likes=max(1, views // 50), comments=max(1, views // 500),
        published_at=NOW - timedelta(days=index * 20), raw=raw,
    )


def _rich_case():
    primary = PlatformAccount(
        platform="youtube", handle="verified_creator",
        url="https://youtube.com/@verified_creator", followers=100_000,
        bio="Business enquiries: hello@creator.example",
        external_links=["https://creator.example/contact"],
        content=[_item(i, views=8_000 + i * 1_000, brand="Acme" if i == 2 else None)
                 for i in range(1, 10)],
        raw={"identity_role": "primary", "analysis_eligible": True},
    )
    raw = RawProfile(
        seed_url=primary.url, seed_platform="youtube", seed_handle=primary.handle,
        display_name="Verified Creator", accounts=[primary],
    )
    signals = SimpleNamespace(
        total_audience=100_000, followers={"youtube": 100_000},
        topic_rank=[("business", .6), ("technology", .4)],
        topic_evidence_total=20, topic_distinct_terms=7,
    )
    audience = SimpleNamespace(
        age=Distribution(buckets={"18-24": 60, "25-34": 40}, confidence=.9,
                         status=ClaimStatus.OBSERVED, method="creator analytics export", sample_size=10_000),
        gender=Distribution(buckets={}, status=ClaimStatus.UNAVAILABLE),
    )
    comments = SimpleNamespace(
        available=True, sample_size=100, duplicate_rate=5, top_author_share=8,
        buckets=[SimpleNamespace(label="Buying intent", count=20, share=20)],
    )
    competitors = SimpleNamespace(competitors=[
        SimpleNamespace(handle="peer_b", display_name="Peer B", platform="youtube",
                        url="https://youtube.com/@peer_b", followers=90_000, content_overlap=70),
        SimpleNamespace(handle="peer_a", display_name="Peer A", platform="instagram",
                        url="https://instagram.com/peer_a", followers=150_000, content_overlap=70),
    ])
    content = SimpleNamespace(
        trend_eligible=True, current_median=15_000, catalogue_median=10_000,
        current_sample=5, historical_sample=5,
    )
    brand = SimpleNamespace(total=32, pillars=[1, 2, 3, 4, 5])
    return raw, signals, audience, content, competitors, comments, brand


def test_rich_result_is_deterministic_auditable_and_json_safe():
    args = _rich_case()
    first = analyse_agency_intelligence(
        args[0], signals=args[1], audience=args[2], content=args[3],
        competitors=args[4], comments=args[5], brand=args[6],
    ).to_dict()
    second = analyse_agency_intelligence(
        args[0], signals=args[1], audience=args[2], content=args[3],
        competitors=args[4], comments=args[5], brand=args[6],
    ).to_dict()

    assert first == second
    json.dumps(first, sort_keys=True)
    assert first["demographics"]["status"] == "observed"
    assert first["engagement"]["status"] == "calculated"
    assert first["estimated_reach"]["status"] == "modelled"
    assert first["contact_details"]["value"][0]["value"] == "hello@creator.example"
    assert first["brand_collaborations"]["value"]["named_brands"] == ["Acme"]
    assert first["historical_performance"]["value"]["change_pct"] == 50.0
    assert first["influence_score"]["value"]["component_coverage_pct"] == 100
    for name, metric in first.items():
        if name == "methodology_version":
            continue
        assert metric["status"] in {"observed", "calculated", "modelled", "unavailable"}
        assert metric["formula"]
        assert metric["denominator"]
        assert 0 <= metric["confidence"] <= 1


def test_sparse_and_walled_data_stays_unavailable_instead_of_becoming_a_guess():
    account = PlatformAccount(
        platform="instagram", handle="walled", url="https://instagram.com/walled",
        followers=None, needs_manual=True,
        errors=["login wall"], raw={"identity_role": "primary", "analysis_eligible": True},
    )
    raw = RawProfile(seed_url=account.url, seed_platform="instagram", accounts=[account])
    result = analyse_agency_intelligence(raw, signals=SimpleNamespace(
        total_audience=0, followers={}, topic_rank=[], topic_evidence_total=0,
        topic_distinct_terms=0,
    )).to_dict()

    assert result["demographics"]["status"] == "unavailable"
    assert result["engagement"]["status"] == "unavailable"
    assert result["audience_quality"]["status"] == "unavailable"
    assert result["fake_follower_anomaly"]["status"] == "unavailable"
    assert result["estimated_reach"]["status"] == "unavailable"
    assert result["historical_performance"]["status"] == "unavailable"
    assert result["influence_score"]["status"] == "unavailable"


def test_zero_denominators_never_raise_or_emit_infinite_values():
    zero_items = [ContentItem(platform="youtube", title=f"zero {i}", views=0,
                              likes=10, comments=2, url=f"https://youtu.be/zero{i}")
                  for i in range(8)]
    account = PlatformAccount(platform="youtube", handle="zero",
                              url="https://youtube.com/@zero", followers=0,
                              content=zero_items, raw={"identity_role": "primary"})
    raw = RawProfile(seed_url=account.url, seed_platform="youtube", accounts=[account])
    result = analyse_agency_intelligence(
        raw, signals=SimpleNamespace(total_audience=0, followers={}, topic_rank=[]),
    ).to_dict()
    encoded = json.dumps(result, allow_nan=False)

    assert "Infinity" not in encoded
    assert result["engagement"]["status"] == "unavailable"
    assert result["estimated_reach"]["status"] == "unavailable"


def test_unrelated_press_page_cannot_supply_contacts_or_collaborations():
    creator = PlatformAccount(
        platform="instagram", handle="real", url="https://instagram.com/real",
        followers=50_000,
        content=[ContentItem(platform="instagram", title="A normal product review",
                             url="https://instagram.com/p/mention", views=5_000,
                             raw={"brand": "MentionedBrand"})],
        raw={"identity_role": "primary", "analysis_eligible": True},
    )
    press = PlatformAccount(
        platform="website", handle="press", url="https://news.example/story",
        bio="Reporter: newsroom@news.example",
        content=[ContentItem(platform="website", title="#ad sponsored by FakeBrand",
                             url="https://news.example/story", views=100_000,
                             raw={"paid_partnership": True, "brand": "FakeBrand"})],
        raw={"identity_role": "independent_evidence", "analysis_eligible": False,
             "brand_collaborations": ["FakeBrand"]},
    )
    raw = RawProfile(seed_url=creator.url, seed_platform="instagram", accounts=[creator, press])
    result = analyse_agency_intelligence(
        raw, signals=SimpleNamespace(total_audience=50_000, followers={"instagram": 50_000}, topic_rank=[]),
    ).to_dict()

    assert result["contact_details"]["status"] == "unavailable"
    assert result["brand_collaborations"]["status"] == "unavailable"
    assert "newsroom@news.example" not in json.dumps(result)
    assert "FakeBrand" not in json.dumps(result)
    assert "MentionedBrand" not in json.dumps(result)


def test_fake_follower_output_is_anomaly_range_never_fake_follower_percentage():
    raw, signals, audience, content, competitors, comments, brand = _rich_case()
    metric = analyse_agency_intelligence(
        raw, signals=signals, audience=audience, content=content,
        competitors=competitors, comments=comments, brand=brand,
    ).fake_follower_anomaly

    assert metric.status == "modelled"
    assert metric.value["estimated_fake_follower_percent"] is None
    assert len(metric.value["risk_score_range"]) == 2
    assert "not the share or count of fake followers" in metric.interpretation


def test_overlap_is_explicitly_unavailable_while_lookalikes_are_ranked():
    _, signals, _, _, competitors, _, _ = _rich_case()
    ranked = rank_lookalike_creators(signals, competitors)
    assert [row["handle"] for row in ranked] == ["peer_b", "peer_a"]

    empty_raw = RawProfile(seed_url="https://youtube.com/@x", seed_platform="youtube")
    result = analyse_agency_intelligence(
        empty_raw, signals=signals, competitors=competitors,
    ).to_dict()
    assert result["audience_overlap"]["status"] == "modelled"
    assert result["audience_overlap"]["value"]["exact_overlap_status"] == "unavailable"
    assert result["audience_overlap"]["value"]["exact_shared_audience_pct"] is None
    assert all("shared followers" in row["scope"] for row in result["lookalike_creators"]["value"])
