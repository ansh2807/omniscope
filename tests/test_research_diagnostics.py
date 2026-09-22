"""Regression tests for the engine's second-order research diagnostics."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

from app.engine import pipeline
from app.engine.collectors import youtube
from app.engine.collectors.comments import Comment
from app.engine.inference import comments as comment_analysis
from app.schemas import ContentItem, PlatformAccount, RawProfile


def _profile() -> RawProfile:
    now = datetime(2026, 8, 5)
    views = [100, 200, 300, 400, 500, 600, 700, 8_000]
    items = [ContentItem(
        platform="youtube", title=f"How to score {i + 1} points" if i < 4 else f"Topic lesson {i + 1}",
        url=f"https://youtube.com/watch?v=test{i:02d}", views=value,
        duration_seconds=45 if i % 2 else 600, kind="short" if i % 2 else "video",
        published_at=now - timedelta(days=sum(range(1, i + 2))),
        raw={"sample": ["latest"]},
    ) for i, value in enumerate(views)]
    return RawProfile(
        seed_url="https://youtube.com/@diagnostic", seed_platform="youtube",
        seed_handle="diagnostic", display_name="Diagnostic Creator",
        accounts=[
            PlatformAccount(platform="youtube", handle="diagnostic",
                            url="https://youtube.com/@diagnostic", followers=75_000,
                            content=items),
            PlatformAccount(platform="instagram", handle="diagnostic",
                            url="https://instagram.com/diagnostic", followers=25_000),
        ],
    )


def test_distribution_platform_and_publishing_diagnostics_are_calculated():
    d = pipeline.analyse(_profile(), "diagnostic-test").diagnostics
    assert d.content_n == 8
    assert d.view_p25 < d.view_median < d.view_p75
    assert d.view_gini > .5
    assert d.top20_share > 70
    assert d.breakout_rate == 12
    assert d.platform_hhi == .625
    assert d.effective_platforms == 1.6
    assert d.median_gap_days is not None and d.p90_gap_days >= d.median_gap_days
    assert d.burstiness is not None
    assert d.lorenz[0] == {"x": 0, "y": 0}
    assert d.lorenz[-1] == {"x": 100.0, "y": 100.0}


def test_diagnostic_score_is_coverage_not_false_completeness():
    d = pipeline.analyse(_profile(), "coverage-test").diagnostics
    assert 0 < d.evidence_score < 100
    assert d.evidence_counts["unavailable"] >= 4
    assert any(x.dimension == "Conversion, revenue and retention"
               and x.status == "unavailable" for x in d.evidence_dimensions)
    assert any(x["metric"] == "View Gini" for x in d.formula_glossary)


def test_comment_diagnostics_add_intervals_and_sample_quality_checks():
    rows = [
        Comment("Great and helpful, what is the price?", author="A"),
        Comment("Great and helpful, what is the price?", author="A"),
        Comment("This badminton lesson is clear", author="B"),
        Comment("Not good, please explain again?", author="C"),
    ]
    ca = comment_analysis.analyse(rows)
    assert ca.unique_authors == 3
    assert ca.top_author_share == 50
    assert ca.duplicate_rate == 25
    assert ca.question_rate == 75
    assert ca.sentiment_ci["positive"][0] <= ca.sentiment["positive"] <= ca.sentiment_ci["positive"][1]
    buying = next(b for b in ca.buckets if b.label == "Buying intent")
    assert buying.ci_low <= buying.share <= buying.ci_high


def test_youtube_api_uses_uploads_playlist_for_latest_and_expands_samples(monkeypatch):
    calls = []

    class Response:
        def __init__(self, payload):
            self.ok, self.text = True, json.dumps(payload)

    async def fake_fetch(url, **kwargs):
        calls.append(url)
        if "/channels?" in url:
            return Response({"items": [{"id": "UC123", "snippet": {"title": "X"},
                             "statistics": {"subscriberCount": "10", "videoCount": "2"},
                             "brandingSettings": {"channel": {}},
                             "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}]})
        if "/playlistItems?" in url:
            return Response({"items": [{"contentDetails": {"videoId": "latest1"}}]})
        if "/search?" in url:
            return Response({"items": [{"id": {"videoId": "popular1"}}]})
        return Response({"items": []})

    monkeypatch.setattr(youtube.settings, "youtube_api_key", "test-key")
    monkeypatch.setattr(youtube, "fetch", fake_fetch)
    account = asyncio.run(youtube._via_api("creator"))
    assert account.raw["content_scope"] == "latest_50_plus_popular_50"
    assert any("/playlistItems?" in url and "maxResults=50" in url for url in calls)
    assert not any("order=date" in url for url in calls)
    assert any("order=viewCount" in url and "maxResults=50" in url for url in calls)
