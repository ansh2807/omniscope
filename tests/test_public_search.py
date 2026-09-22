"""Public analyze form: optional guest Serper key, free path still works."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import main
from app.engine.discovery import search as search_mod
from app.models import Job
from app.omni.search_context import bind_serper_key, guest_serper_key, reset_serper_key
from tests.test_data_hygiene import _isolated, _restore


def test_home_offers_free_path_and_serper():
    html = TestClient(main.app).get("/").text
    assert "Free — no key" in html
    assert "I have a Serper key" in html
    assert "stripe.com" in html
    assert "data-fill" in html
    assert "Remember this key on this device" in html
    assert "search_mode" in html


def test_serper_mode_without_key_is_rejected(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        client = TestClient(main.app)
        resp = client.post("/generate", data={
            "url": "https://example.com",
            "email": "ada@firm.com",
            "search_mode": "serper",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert "err=key" in resp.headers.get("location", "")
    finally:
        _restore(state)


def test_guest_serper_key_is_not_stored_on_the_job(tmp_path):
    engine, state = _isolated(tmp_path)
    secret = "guest-serper-key-xyz"
    try:
        client = TestClient(main.app)
        resp = client.post("/generate", data={
            "url": "https://example.com",
            "email": "ada@firm.com",
            "search_mode": "serper",
            "serper_key": secret,
        }, follow_redirects=False)
        assert resp.status_code == 303
        job_id = resp.headers["location"].rsplit("/", 1)[-1]
        with Session(engine) as db:
            job = db.get(Job, job_id)
            assert job is not None
            dumped = " ".join(str(v) for v in job.model_dump().values())
            assert secret not in dumped
            assert job.recipient_email == "ada@firm.com"
    finally:
        _restore(state)


def test_guest_serper_key_enables_search_without_settings():
    from app.config import settings
    old = (settings.search_provider, settings.serper_api_key)
    settings.search_provider = "none"
    settings.serper_api_key = ""
    token = bind_serper_key("guest-serper-key-xyz")
    try:
        assert guest_serper_key() == "guest-serper-key-xyz"
        assert search_mod._available_providers() == ["serper"]
    finally:
        reset_serper_key(token)
        settings.search_provider, settings.serper_api_key = old
        assert guest_serper_key() == ""
