"""Keyless official-site parsers and keyword resolve order."""
from __future__ import annotations

import asyncio

from app.omni.competitors import pick_competitors
from app.omni.keyless_web import (official_from_ddg_hits, p856_matches_domain,
                                  parse_ddg_hits, parse_wikidata_official,
                                  pick_wikidata_id)
from app.omni.nexus import resolve_keyword
from app.schemas import SearchHit


def test_wikidata_p856_skips_wikipedia():
    entity = {
        "claims": {
            "P856": [
                {"mainsnak": {"datavalue": {
                    "value": "https://en.wikipedia.org/wiki/Acme"}}},
                {"mainsnak": {"datavalue": {"value": "https://www.acme.com/"}}},
            ]
        }
    }
    assert parse_wikidata_official(entity) == "https://www.acme.com/"
    assert p856_matches_domain(entity, "acme.com") is True
    assert p856_matches_domain(entity, "other.com") is False
    assert pick_wikidata_id(
        {"search": [{"id": "Q1", "label": "Acme Corp"}]}, "Acme Corp") == "Q1"
    assert pick_wikidata_id(
        {"search": [{"id": "Q1", "label": "Unrelated"}]}, "Acme Corp") == ""


def test_ddg_related_topics_become_hits():
    payload = {
        "Heading": "Acme",
        "AbstractURL": "https://www.acme.com/",
        "RelatedTopics": [
            {"FirstURL": "https://rival.example/", "Text": "Rival — billing software"},
            {"Name": "See also", "Topics": [
                {"FirstURL": "https://en.wikipedia.org/wiki/X", "Text": "X"},
            ]},
        ],
    }
    hits = parse_ddg_hits(payload, "Acme alternatives")
    urls = [h.url for h in hits]
    assert "https://www.acme.com/" in urls
    assert "https://rival.example/" in urls
    assert all("wikipedia.org" not in u for u in urls)
    assert official_from_ddg_hits(hits, "Acme") == "https://www.acme.com/"
    rivals = pick_competitors(hits, "acme.com")
    assert [r.domain for r in rivals] == ["rival.example"]


def test_resolve_keyword_uses_keyless_before_search(monkeypatch):
    async def fake_keyless(name, skip):
        return "https://www.acme.com/"

    async def boom(*_a, **_k):
        raise AssertionError("licensed search should not run when keyless hits")

    monkeypatch.setattr("app.omni.nexus.resolve_official_site", fake_keyless)
    monkeypatch.setattr("app.engine.discovery.search.search", boom)
    assert asyncio.run(resolve_keyword("Acme Software")) == "https://www.acme.com/"


def test_resolve_keyword_falls_back_to_search(monkeypatch):
    async def empty_keyless(_name, _skip):
        return ""

    async def fake_search(_q, limit=8):
        return [SearchHit(query="q", title="Acme", url="https://acme.io/",
                          snippet="", provider="serper")]

    monkeypatch.setattr("app.omni.nexus.resolve_official_site", empty_keyless)
    monkeypatch.setattr("app.engine.discovery.search.search", fake_search)
    assert asyncio.run(resolve_keyword("Acme Software")) == "https://acme.io/"
