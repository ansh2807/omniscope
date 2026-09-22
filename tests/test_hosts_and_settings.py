"""Host typo hints, homepage degrade, and Sources / Serper save."""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.config import settings
from app.engine.http import Fetched
from app.omni.hosts import fetch_failure_copy, homepage_candidates, suggest_host
from app.omni.market import MarketIntel
from app.omni.news import NewsIntel
from app.omni.open_sources import OpenSourceIntel
from app.omni.webintel import analyse
from app import main
from tools import envfile


def test_punchub_suggests_pornhub():
    assert suggest_host("punchub.com") == "pornhub.com"
    assert suggest_host("www.punchhub.com") == "pornhub.com"
    assert suggest_host("pornhub.com") == ""
    copy = fetch_failure_copy("punchub.com", "ConnectError")
    assert "punchub.com" in copy
    assert "pornhub.com" in copy


def test_homepage_candidates_try_www_and_http():
    urls = homepage_candidates("https://punchub.com/")
    assert urls[0] == "https://punchub.com/"
    assert "https://www.punchub.com/" in urls
    assert "http://punchub.com/" in urls


def test_analyse_degrades_when_host_is_dead(monkeypatch):
    async def dead(url, **_kwargs):
        return Fetched(url=url, status=0, text="", error="ConnectError")

    async def skip_news(*_a, **_k):
        return NewsIntel(assessed=False, reason="test")

    async def skip_market(*_a, **_k):
        return MarketIntel(assessed=False, reason="test")

    async def skip_open(*_a, **_k):
        return OpenSourceIntel(assessed=False, reason="test")

    monkeypatch.setattr("app.omni.webintel.fetch", dead)
    monkeypatch.setattr("app.omni.news.scan", skip_news)
    monkeypatch.setattr("app.omni.market.scan", skip_market)
    monkeypatch.setattr("app.omni.open_sources.collect", skip_open)

    payload = asyncio.run(analyse(
        "https://punchub.com", "rep-dead",
        collect_socials=False, with_competitors=False))
    assert payload.domain == "punchub.com"
    assert payload.pages == []
    joined = " ".join(payload.warnings)
    assert "pornhub.com" in joined
    assert "punchub.com" in joined


def test_envfile_writes_runtime_not_project_env(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(settings, "reports_dir", str(reports))
    monkeypatch.setattr(envfile, "ENV", tmp_path / "project.env")
    changed = envfile.write({"SERPER_API_KEY": "runtime-only-key"})
    assert "SERPER_API_KEY" in changed
    assert "runtime-only-key" in (tmp_path / "runtime.env").read_text(encoding="utf-8")
    assert not (tmp_path / "project.env").exists()


def test_settings_saves_serper_with_operator_token(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    old = (settings.reports_dir, settings.admin_token,
           settings.serper_api_key, settings.search_provider)
    monkeypatch.setattr(envfile, "ENV", tmp_path / "project.env")
    settings.reports_dir = str(reports)
    settings.admin_token = "op-secret-token"
    settings.serper_api_key = ""
    settings.search_provider = "none"
    try:
        client = TestClient(main.app)
        page = client.get("/settings")
        assert page.status_code == 200
        assert "serper.dev" in page.text
        assert "Sources" in page.text or "Operator token" in page.text

        denied = client.post("/settings", data={
            "operator_token": "short",
            "SERPER_API_KEY": "should-not-save",
        })
        assert denied.status_code == 200
        assert "Operator token is required" in denied.text
        assert settings.serper_api_key == ""

        saved = client.post("/settings", data={
            "operator_token": "op-secret-token",
            "SERPER_API_KEY": "serper-test-key",
        }, follow_redirects=False)
        assert saved.status_code == 303
        assert settings.serper_api_key == "serper-test-key"
        assert settings.search_provider == "serper"
        assert "serper-test-key" in (tmp_path / "runtime.env").read_text(encoding="utf-8")
        assert saved.cookies.get("ci_admin") == "op-secret-token"

        naked = TestClient(main.app)
        public = naked.get("/settings")
        assert public.status_code == 200
        assert "serper-test-key" not in public.text
    finally:
        (settings.reports_dir, settings.admin_token,
         settings.serper_api_key, settings.search_provider) = old
