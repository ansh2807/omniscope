"""Application-level regressions not covered by the inference fixtures."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app import db as db_module
from app import main
from app.commercial.models import LicenseKey, Org
from app.models import Job, Report
from app.schemas import RawProfile
from tests import fixtures


def _isolated_app(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'app.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    old_main_engine, old_db_engine = main.db_engine, db_module.engine
    old_reports = main.settings.reports_dir
    main.db_engine = engine
    db_module.engine = engine
    main.settings.reports_dir = str(tmp_path / "reports")
    return engine, (old_main_engine, old_db_engine, old_reports)


def _restore(state) -> None:
    main.db_engine, db_module.engine, main.settings.reports_dir = state


def test_customer_keys_cannot_read_or_delete_another_orgs_work(tmp_path):
    engine, state = _isolated_app(tmp_path)
    try:
        with Session(engine) as db:
            owner = Org(id="org_owner", name="Owner", email="owner@example.com")
            stranger = Org(id="org_stranger", name="Stranger", email="stranger@example.com")
            db.add(owner); db.add(stranger)
            db.add(LicenseKey(key="CI-AAAA-AAAA-AAAA-AAAA", org_id=owner.id))
            db.add(LicenseKey(key="CI-BBBB-BBBB-BBBB-BBBB", org_id=stranger.id))
            db.add(Job(id="privatejob", seed_url="https://example.com", org_id=owner.id))
            db.add(Report(
                id="privatereport", job_id="privatejob", share_slug="owner-report",
                org_id=owner.id, subject_name="Owner creator", subject_handle="owner",
                seed_url="https://example.com", html_path=str(tmp_path / "report.html"),
            ))
            db.commit()

        client = TestClient(main.app)
        stranger_headers = {"x-license-key": "CI-BBBB-BBBB-BBBB-BBBB"}
        owner_headers = {"x-license-key": "CI-AAAA-AAAA-AAAA-AAAA"}

        assert client.get("/api/jobs/privatejob", headers=stranger_headers).status_code == 404
        assert client.get("/api/reports", headers=stranger_headers).json() == []
        assert client.post("/reports/privatereport/delete", headers=stranger_headers,
                           follow_redirects=False).status_code == 404
        assert client.get("/api/jobs/privatejob", headers=owner_headers).status_code == 200
        assert [row["id"] for row in client.get("/api/reports", headers=owner_headers).json()] == ["privatereport"]

        with Session(engine) as db:
            assert db.get(Report, "privatereport") is not None
    finally:
        _restore(state)


def test_manual_enrichment_regenerates_in_place(tmp_path):
    """Optional evidence must not create a duplicate report or a second billable run."""
    engine, state = _isolated_app(tmp_path)
    try:
        with Session(engine) as db:
            db.add(Job(id="regenjob", seed_url="https://example.com"))
            db.commit()

        raw = fixtures.chanchal_singh()
        asyncio.run(main._finalise("regenjob", [raw]))
        with Session(engine) as db:
            first = db.exec(select(Report).where(Report.job_id == "regenjob")).all()
            assert len(first) == 1
            identity = first[0].id, first[0].share_slug

        instagram = next(a for a in raw.accounts if a.platform == "instagram")
        instagram.followers += 100
        asyncio.run(main._finalise("regenjob", [raw]))
        with Session(engine) as db:
            regenerated = db.exec(select(Report).where(Report.job_id == "regenjob")).all()
            assert len(regenerated) == 1
            assert (regenerated[0].id, regenerated[0].share_slug) == identity
    finally:
        _restore(state)


def test_different_creator_jobs_never_reuse_the_same_report(tmp_path):
    """Regression for the production bug where a new creator link returned an old report."""
    engine, state = _isolated_app(tmp_path)
    try:
        with Session(engine) as db:
            db.add(Job(id="suniljob", seed_url=fixtures.sunil_panda().seed_url))
            db.add(Job(id="ishaanjob", seed_url=fixtures.ishaan_arora().seed_url))
            db.commit()

        asyncio.run(main._finalise("suniljob", [fixtures.sunil_panda()]))
        asyncio.run(main._finalise("ishaanjob", [fixtures.ishaan_arora()]))

        with Session(engine) as db:
            sunil = db.exec(select(Report).where(Report.job_id == "suniljob")).one()
            ishaan = db.exec(select(Report).where(Report.job_id == "ishaanjob")).one()
            assert sunil.id != ishaan.id
            assert sunil.share_slug != ishaan.share_slug
            assert sunil.html_path != ishaan.html_path
            assert sunil.subject_name == "Sunil Panda"
            assert ishaan.subject_name == "Ishaan Arora"
            assert "Sunil Panda" in Path(sunil.html_path).read_text(encoding="utf-8")
            assert "Ishaan Arora" in Path(ishaan.html_path).read_text(encoding="utf-8")
    finally:
        _restore(state)


def test_collection_does_not_pause_for_missing_instagram_followers(tmp_path, monkeypatch):
    engine, state = _isolated_app(tmp_path)
    try:
        raw = fixtures.chanchal_singh()
        ig = next(a for a in raw.accounts if a.platform == "instagram")
        ig.followers = None
        with Session(engine) as db:
            db.add(Job(id="igjob", seed_url="https://www.instagram.com/democreator/"))
            db.commit()

        async def fake_collect(*_a, **_k):
            return raw

        monkeypatch.setattr(main.pipeline, "collect", fake_collect)
        asyncio.run(main._run_collection_body(
            "igjob", ["https://www.instagram.com/democreator/"], False, False,
            lambda *_a, **_k: None))
        with Session(engine) as db:
            job = db.get(Job, "igjob")
            assert job.status == "done"
            assert db.exec(select(Report).where(Report.job_id == "igjob")).first()
    finally:
        _restore(state)


def test_skip_finalises_without_inventing_followers(tmp_path):
    engine, state = _isolated_app(tmp_path)
    try:
        raw = fixtures.chanchal_singh()
        ig = next(a for a in raw.accounts if a.platform == "instagram")
        ig.followers = None
        with Session(engine) as db:
            db.add(Job(
                id="skipjob",
                seed_url=raw.seed_url,
                status="needs_input",
                raw_json=json.dumps([raw.model_dump_json()]),
            ))
            db.commit()
        client = TestClient(main.app)
        resp = client.post("/jobs/skipjob/skip", follow_redirects=False)
        assert resp.status_code == 303
        with Session(engine) as db:
            job = db.get(Job, "skipjob")
            assert job.status == "done"
            stored = RawProfile.model_validate_json(json.loads(job.raw_json)[0])
            ig2 = next(a for a in stored.accounts if a.platform == "instagram")
            assert ig2.followers is None
            assert db.exec(select(Report).where(Report.job_id == "skipjob")).first()
    finally:
        _restore(state)


def test_stuck_needs_input_offers_continue_not_required_entry(tmp_path):
    engine, state = _isolated_app(tmp_path)
    try:
        with Session(engine) as db:
            db.add(Job(
                id="stuckjob",
                seed_url="https://www.instagram.com/democreator/",
                status="needs_input",
                raw_json='{"x": 1}',
            ))
            db.commit()
        client = TestClient(main.app)
        html = client.get("/jobs/stuckjob").text
        assert "Continue without it" in html
        assert "Enter it" not in html
        assert "ENABLE-BROWSER.bat" not in html
        assert "report cannot be built" not in html
    finally:
        _restore(state)
