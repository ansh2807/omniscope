from __future__ import annotations

from types import SimpleNamespace

from app.engine.discovery.creator_search import _extract
from app.engine.inference.media_buy import build_media_buy_scorecard
from app.engine import pipeline
from tests import fixtures


def test_extract_clean_profiles_only():
    assert _extract("https://www.instagram.com/sunilpandaofficial/", None)[0] == "instagram"
    assert _extract("https://www.youtube.com/@veritasium", "youtube")[1].endswith("@veritasium")
    assert _extract("https://www.instagram.com/p/AbCdEf/", None) is None
    assert _extract("https://www.youtube.com/watch?v=abc", None) is None


def test_media_buy_scorecard_on_fixture():
    payload = pipeline.analyse(fixtures.sunil_panda(), "mb-sunil")
    assert payload.media_buy is not None
    assert payload.media_buy["verdict"] in {
        "prioritize", "pilot", "hold", "pass", "insufficient_evidence",
    }
    assert payload.media_buy["coverage_pct"] > 0
    assert payload.agency is not None
    assert "audience_quality" in payload.agency


def test_media_buy_handles_empty_agency():
    card = build_media_buy_scorecard(
        agency={},
        signals=SimpleNamespace(total_audience=0, followers={}),
        content=None, brand=None, diagnostics=None, audience=None,
    )
    assert card["verdict"] == "insufficient_evidence"
    assert card["fit_score"] is None
