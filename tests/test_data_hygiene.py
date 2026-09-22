"""Data-hygiene regressions.

Deletion must be complete and must report itself honestly: a report leaves together
with the job that collected it (the job row holds the raw data), a purge empties the
reports directory and the whole cache, and both destructive operator actions land in
the audit log. Cohort reports carry a real per-subject join key so per-creator
lookups and future erasure never fall back to the "N creators" display label.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app import db as db_module
from app import main
from app.commercial.models import AuditLog, LicenseKey, Org
from app.config import settings
from app.models import Job, JobStatus, Report, ShortlistItem
from tests import fixtures


def _isolated(tmp_path: Path, *, operator_key: str | None = None):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'app.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    old = (main.db_engine, db_module.engine,
           settings.reports_dir, settings.cache_dir, settings.api_keys)
    main.db_engine = engine
    db_module.engine = engine
    (tmp_path / "reports").mkdir(exist_ok=True)
    (tmp_path / "cache").mkdir(exist_ok=True)
    settings.reports_dir = str(tmp_path / "reports")
    settings.cache_dir = str(tmp_path / "cache")
    if operator_key:
        settings.api_keys = operator_key
    return engine, old


def _restore(state) -> None:
    (main.db_engine, db_module.engine, settings.reports_dir, settings.cache_dir,
     settings.api_keys) = state


def _make_report(tmp_path: Path, rid: str, job_id: str, *, days_old: int = 0,
                 minutes_old: int = 0,
                 kind: str = "single", handle: str = "@creator",
                 org_id: str | None = None, payload_json: str | None = None) -> Report:
    html = tmp_path / "reports" / f"{rid}.html"
    html.write_text("<html>report</html>", encoding="utf-8")
    return Report(
        id=rid, job_id=job_id, share_slug=f"slug-{rid}", subject_name="Creator",
        subject_handle=handle, seed_url="https://example.com", kind=kind,
        org_id=org_id, html_path=str(html), payload_json=payload_json,
        created_at=datetime.utcnow() - timedelta(days=days_old, minutes=minutes_old))


# ------------------------------------------------------------------ sweep / purge

def test_sweep_deletes_the_job_with_its_doomed_report(tmp_path):
    engine, state = _isolated(tmp_path)
    old_ret, old_max, old_ttl = (
        settings.retention_days, settings.max_reports, settings.report_ttl_minutes)
    settings.retention_days, settings.max_reports, settings.report_ttl_minutes = 30, 0, 0
    try:
        with Session(engine) as db:
            db.add(Job(id="oldjob", seed_url="https://example.com",
                       status=JobStatus.DONE.value, raw_json='{"secret": true}',
                       created_at=datetime.utcnow() - timedelta(days=60)))
            db.add(_make_report(tmp_path, "oldreport", "oldjob", days_old=60))
            db.add(Job(id="freshjob", seed_url="https://example.com",
                       status=JobStatus.DONE.value, raw_json='{"secret": true}'))
            db.add(_make_report(tmp_path, "freshreport", "freshjob"))
            db.commit()

        from tools import housekeeping
        swept = housekeeping.sweep(engine)

        assert swept.reports_deleted == 1
        assert swept.jobs_deleted == 1
        with Session(engine) as db:
            assert db.get(Report, "oldreport") is None
            assert db.get(Job, "oldjob") is None      # raw data leaves with the report
            assert db.get(Report, "freshreport") is not None
            assert db.get(Job, "freshjob") is not None
        assert not (tmp_path / "reports" / "oldreport.html").exists()
        assert (tmp_path / "reports" / "freshreport.html").exists()
    finally:
        settings.retention_days, settings.max_reports, settings.report_ttl_minutes = (
            old_ret, old_max, old_ttl)
        _restore(state)


def test_sweep_prunes_abandoned_jobs_but_never_in_flight(tmp_path):
    engine, state = _isolated(tmp_path)
    old_ret, old_max, old_ttl = (
        settings.retention_days, settings.max_reports, settings.report_ttl_minutes)
    settings.retention_days, settings.max_reports, settings.report_ttl_minutes = 30, 0, 0
    try:
        old = datetime.utcnow() - timedelta(days=60)
        with Session(engine) as db:
            db.add(Job(id="stalefailed", seed_url="u", status=JobStatus.FAILED.value,
                       raw_json='{"x": 1}', created_at=old))
            db.add(Job(id="stalewaiting", seed_url="u",
                       status=JobStatus.NEEDS_INPUT.value, raw_json='{"x": 1}',
                       created_at=old))
            db.add(Job(id="stalequeued", seed_url="u", status=JobStatus.QUEUED.value,
                       created_at=old))
            db.add(Job(id="stalerunning", seed_url="u", status=JobStatus.RUNNING.value,
                       created_at=old))
            db.commit()

        from tools import housekeeping
        swept = housekeeping.sweep(engine)

        assert swept.jobs_deleted == 2
        with Session(engine) as db:
            assert db.get(Job, "stalefailed") is None
            assert db.get(Job, "stalewaiting") is None
            assert db.get(Job, "stalequeued") is not None    # in flight: never pruned
            assert db.get(Job, "stalerunning") is not None
    finally:
        settings.retention_days, settings.max_reports, settings.report_ttl_minutes = (
            old_ret, old_max, old_ttl)
        _restore(state)


def test_sweep_deletes_report_after_five_minutes(tmp_path):
    engine, state = _isolated(tmp_path)
    old = (settings.report_ttl_minutes, settings.retention_days, settings.max_reports)
    settings.report_ttl_minutes, settings.retention_days, settings.max_reports = 5, 0, 0
    try:
        with Session(engine) as db:
            db.add(Job(id="oldjob", seed_url="u", status=JobStatus.DONE.value,
                       raw_json='{"secret": true}',
                       created_at=datetime.utcnow() - timedelta(minutes=6)))
            db.add(_make_report(tmp_path, "oldreport", "oldjob", minutes_old=6))
            db.add(Job(id="freshjob", seed_url="u", status=JobStatus.DONE.value,
                       raw_json='{"secret": true}'))
            db.add(_make_report(tmp_path, "freshreport", "freshjob"))
            db.commit()

        from tools import housekeeping
        swept = housekeeping.sweep(engine)

        assert swept.reports_deleted == 1
        assert swept.jobs_deleted == 1
        with Session(engine) as db:
            assert db.get(Report, "oldreport") is None
            assert db.get(Job, "oldjob") is None
            assert db.get(Report, "freshreport") is not None
        assert not (tmp_path / "reports" / "oldreport.html").exists()
        assert (tmp_path / "reports" / "freshreport.html").exists()
    finally:
        (settings.report_ttl_minutes, settings.retention_days,
         settings.max_reports) = old
        _restore(state)


def test_html_download_works_inside_ttl_window(tmp_path):
    engine, state = _isolated(tmp_path)
    old_ttl = settings.report_ttl_minutes
    settings.report_ttl_minutes = 5
    try:
        with Session(engine) as db:
            db.add(Job(id="job", seed_url="u", status=JobStatus.DONE.value))
            db.add(_make_report(tmp_path, "fresh", "job",
                                payload_json='{"kind":"web"}'))
            db.commit()
        client = TestClient(main.app)
        resp = client.get("/r/slug-fresh.html")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "").lower()
        assert b"<html>report</html>" in resp.content
        live = client.get("/r/slug-fresh")
        assert live.status_code == 200
        assert b"Download HTML" in live.content
        assert b"omni-ttl" in live.content
    finally:
        settings.report_ttl_minutes = old_ttl
        _restore(state)


def test_expired_share_link_is_gone(tmp_path):
    engine, state = _isolated(tmp_path)
    old_ttl = settings.report_ttl_minutes
    settings.report_ttl_minutes = 5
    try:
        with Session(engine) as db:
            db.add(Job(id="job", seed_url="u", status=JobStatus.DONE.value,
                       raw_json='{"secret": true}',
                       created_at=datetime.utcnow() - timedelta(minutes=6)))
            db.add(_make_report(tmp_path, "old", "job", minutes_old=6,
                                payload_json='{"kind":"web"}'))
            db.commit()
        client = TestClient(main.app)
        gone = client.get("/r/slug-old")
        assert gone.status_code == 410
        assert b"deleted" in gone.content.lower()
        with Session(engine) as db:
            assert db.get(Report, "old") is None
            assert db.get(Job, "job") is None
        assert not (tmp_path / "reports" / "old.html").exists()
        assert client.get("/r/slug-old.html").status_code == 404

        with Session(engine) as db:
            db.add(Job(id="job2", seed_url="u", status=JobStatus.DONE.value,
                       created_at=datetime.utcnow() - timedelta(minutes=6)))
            db.add(_make_report(tmp_path, "old2", "job2", minutes_old=6,
                                payload_json='{"kind":"web"}'))
            db.commit()
        assert client.get("/r/slug-old2.html").status_code == 410
        assert client.get("/r/slug-old2.json").status_code == 404
    finally:
        settings.report_ttl_minutes = old_ttl
        _restore(state)


def test_purge_all_leaves_nothing_behind(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        with Session(engine) as db:
            db.add(Job(id="j1", seed_url="u", raw_json='{"x": 1}'))
            db.add(_make_report(tmp_path, "r1", "j1"))
            db.commit()
        (tmp_path / "reports" / "orphan.html").write_text("stale", encoding="utf-8")
        (tmp_path / "cache" / "page.json").write_text("{}", encoding="utf-8")
        (tmp_path / "cache" / "scratch.bin").write_text("bin", encoding="utf-8")

        from tools import housekeeping
        swept = housekeeping.purge_all(engine)

        assert swept.reports_deleted == 1
        assert swept.jobs_deleted == 1
        assert swept.files_deleted == 2        # the report file and the orphan
        assert swept.cache_files_deleted == 2  # json and non-json alike
        with Session(engine) as db:
            assert db.exec(select(Report)).all() == []
            assert db.exec(select(Job)).all() == []
        assert list((tmp_path / "reports").iterdir()) == []
        assert list((tmp_path / "cache").iterdir()) == []
    finally:
        _restore(state)


def test_delete_one_removes_report_job_and_files(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        with Session(engine) as db:
            db.add(Job(id="job", seed_url="u", raw_json='{"x": 1}'))
            db.add(_make_report(tmp_path, "rep", "job"))
            db.commit()

        from tools import housekeeping
        assert housekeeping.delete_one(engine, "rep") is True

        with Session(engine) as db:
            assert db.get(Report, "rep") is None
            assert db.get(Job, "job") is None
        assert not (tmp_path / "reports" / "rep.html").exists()
    finally:
        _restore(state)


def test_delete_one_keeps_a_job_another_report_still_uses(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        with Session(engine) as db:
            db.add(Job(id="shared", seed_url="u", raw_json='{"x": 1}'))
            db.add(_make_report(tmp_path, "first", "shared"))
            db.add(_make_report(tmp_path, "second", "shared"))
            db.commit()

        from tools import housekeeping
        housekeeping.delete_one(engine, "first")
        with Session(engine) as db:
            assert db.get(Job, "shared") is not None   # still referenced
        housekeeping.delete_one(engine, "second")
        with Session(engine) as db:
            assert db.get(Job, "shared") is None
    finally:
        _restore(state)


# ------------------------------------------------------------------ cohort join key

def test_finalise_writes_the_cohort_subject_join_key(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        with Session(engine) as db:
            db.add(Job(id="cohortjob", seed_url=fixtures.sunil_panda().seed_url))
            db.commit()

        asyncio.run(main._finalise(
            "cohortjob", [fixtures.sunil_panda(), fixtures.ishaan_arora()]))

        with Session(engine) as db:
            rep = db.exec(select(Report).where(Report.job_id == "cohortjob")).one()
            assert rep.kind == "cohort"
            assert rep.subject_handle == "2 creators"   # display label, not a key
            subjects = rep.subjects()
            assert len(subjects) == 2
            assert {s["name"] for s in subjects} == {"Sunil Panda", "Ishaan Arora"}
            assert all(s["handle"] and s["handle"] != "2 creators" for s in subjects)
            assert all(s["seed_url"] for s in subjects)
    finally:
        _restore(state)


def test_finalise_single_report_has_one_subject_key(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        with Session(engine) as db:
            db.add(Job(id="singlejob", seed_url=fixtures.sunil_panda().seed_url))
            db.commit()

        asyncio.run(main._finalise("singlejob", [fixtures.sunil_panda()]))

        with Session(engine) as db:
            rep = db.exec(select(Report).where(Report.job_id == "singlejob")).one()
            assert rep.kind == "single"
            subjects = rep.subjects()
            assert len(subjects) == 1
            assert subjects[0]["name"] == "Sunil Panda"
            assert subjects[0]["handle"] == rep.subject_handle
    finally:
        _restore(state)


def test_subjects_tolerates_missing_or_corrupt_json():
    rep = Report(id="x", job_id="j", share_slug="s", subject_name="n",
                 subject_handle="@n", seed_url="u", html_path="x.html")
    rep.subjects_json = None
    assert rep.subjects() == []
    rep.subjects_json = "{not json"
    assert rep.subjects() == []
    rep.subjects_json = '{"a": 1}'
    assert rep.subjects() == []


def _client_with_org(engine, tmp_path) -> TestClient:
    with Session(engine) as db:
        org = Org(id="org1", name="Owner", email="owner@example.com")
        db.add(org)
        db.add(LicenseKey(key="CI-AAAA-AAAA-AAAA-AAAA", org_id=org.id))
        db.commit()
    return TestClient(main.app)


def test_quick_add_single_report_uses_the_real_handle(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        with Session(engine) as db:
            db.add(_make_report(tmp_path, "rep", "job", handle="@realhandle",
                                org_id="org1"))
            db.commit()
        client = _client_with_org(engine, tmp_path)

        resp = client.post("/shortlists/quick-add", data={"report_id": "rep"},
                           headers={"x-license-key": "CI-AAAA-AAAA-AAAA-AAAA"},
                           follow_redirects=False)

        assert resp.status_code == 303
        with Session(engine) as db:
            item = db.exec(select(ShortlistItem)).one()
            assert item.handle == "realhandle"
            assert item.display_name == "Creator"
    finally:
        _restore(state)


def test_quick_add_cohort_report_is_refused(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        with Session(engine) as db:
            db.add(_make_report(tmp_path, "rep", "job", kind="cohort",
                                handle="2 creators", org_id="org1"))
            db.commit()
        client = _client_with_org(engine, tmp_path)

        resp = client.post("/shortlists/quick-add", data={"report_id": "rep"},
                           headers={"x-license-key": "CI-AAAA-AAAA-AAAA-AAAA"},
                           follow_redirects=False)

        assert resp.status_code == 422
        with Session(engine) as db:
            assert db.exec(select(ShortlistItem)).all() == []
    finally:
        _restore(state)


# ------------------------------------------------------------------ audit trail

def test_purge_is_written_to_the_audit_log(tmp_path):
    engine, state = _isolated(tmp_path, operator_key="test-operator-key")
    try:
        with Session(engine) as db:
            db.add(Job(id="j", seed_url="u", raw_json='{"x": 1}'))
            db.add(_make_report(tmp_path, "r", "j"))
            db.commit()
        client = TestClient(main.app)

        resp = client.post("/settings/purge", headers={"x-api-key": "test-operator-key"},
                           follow_redirects=False)

        assert resp.status_code == 303
        with Session(engine) as db:
            assert db.exec(select(Report)).all() == []
            assert db.exec(select(Job)).all() == []
            rows = db.exec(select(AuditLog).where(AuditLog.action == "settings.purge")).all()
            assert len(rows) == 1
            assert rows[0].actor.startswith("key:")
            assert "reports=1" in rows[0].detail
            assert "jobs=1" in rows[0].detail
    finally:
        _restore(state)


def test_report_deletion_is_written_to_the_audit_log(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        with Session(engine) as db:
            org = Org(id="org1", name="Owner", email="owner@example.com")
            db.add(org)
            db.add(LicenseKey(key="CI-AAAA-AAAA-AAAA-AAAA", org_id=org.id))
            db.add(Job(id="j", seed_url="u", org_id=org.id, raw_json='{"x": 1}'))
            db.add(_make_report(tmp_path, "r", "j", org_id=org.id))
            db.commit()
        client = TestClient(main.app)

        resp = client.post("/reports/r/delete",
                           headers={"x-license-key": "CI-AAAA-AAAA-AAAA-AAAA"},
                           follow_redirects=False)

        assert resp.status_code == 303
        with Session(engine) as db:
            assert db.get(Report, "r") is None
            assert db.get(Job, "j") is None
            rows = db.exec(select(AuditLog).where(AuditLog.action == "report.delete")).all()
            assert len(rows) == 1
            assert rows[0].target == "r"
            assert rows[0].actor.startswith("key:")
    finally:
        _restore(state)


# ------------------------------------------------------------------ disclosure

def test_fingerprint_never_contains_credential_material():
    fp = main._fingerprint("supersecret-operator-key")
    assert fp.startswith("key:")
    assert "supersecret" not in fp
    assert fp != "superse"          # the old key[:6] behaviour


def test_healthz_discloses_nothing_but_liveness():
    client = TestClient(main.app)
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert set(body) == {"ok", "app"}


# ------------------------------------------------------------------ public email flow

def test_public_generate_works_without_email(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        client = TestClient(main.app)
        resp = client.post("/generate", data={"url": "https://example.com"},
                           follow_redirects=False)
        assert resp.status_code == 303
        loc = resp.headers["location"]
        assert loc.startswith("/jobs/")
        job_id = loc.rsplit("/", 1)[-1]
        with Session(engine) as db:
            job = db.get(Job, job_id)
            assert job is not None
            assert job.recipient_email is None
            assert job.org_id is None
    finally:
        _restore(state)


def test_public_generate_stores_email_without_an_account(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        client = TestClient(main.app)
        resp = client.post("/generate",
                           data={"url": "https://example.com", "email": "Ada@Firm.COM"},
                           follow_redirects=False)
        assert resp.status_code == 303
        loc = resp.headers["location"]
        assert loc.startswith("/jobs/")
        job_id = loc.rsplit("/", 1)[-1]
        with Session(engine) as db:
            job = db.get(Job, job_id)
            assert job is not None
            assert job.recipient_email == "ada@firm.com"
            assert job.org_id is None
    finally:
        _restore(state)


def test_home_is_email_only_no_accounts():
    client = TestClient(main.app)
    html = client.get("/").text
    assert "Your email" in html
    assert "No account" in html
    assert "Full product" in html
    assert "Start trial" not in html
    assert "licence key" not in html.lower()
    assert settings.app_version in html
    assert "full product, free" in html
    assert "until 3 September 2026" not in html
    assert f"reports deleted after {settings.report_ttl_label}" in html
    assert 'href="/overview"' in html
    assert 'href="/library"' in html
    assert 'href="/digest"' in html


def test_public_product_hubs_are_open():
    client = TestClient(main.app)
    for path in ("/overview", "/library", "/compare", "/research", "/digest",
                 "/alerts", "/entities", "/graph", "/desk"):
        resp = client.get(path)
        assert resp.status_code == 200, path
    assert client.get("/api/v1/providers").status_code == 200
    assert client.get("/api/reports").status_code == 200


def test_public_delete_report_still_needs_a_key(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        with Session(engine) as db:
            db.add(Job(id="keepjob", seed_url="https://example.com"))
            db.add(_make_report(tmp_path, "keepreport", "keepjob"))
            db.commit()
        client = TestClient(main.app)
        resp = client.post("/reports/keepreport/delete", follow_redirects=False)
        assert resp.status_code == 401
        with Session(engine) as db:
            assert db.get(Report, "keepreport") is not None
    finally:
        _restore(state)


def test_public_library_hides_other_orgs_reports(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        with Session(engine) as db:
            db.add(Job(id="pubjob", seed_url="https://example.com"))
            db.add(_make_report(tmp_path, "pubreport", "pubjob", handle="@public"))
            db.add(Job(id="orgjob", seed_url="https://example.com", org_id="org_other"))
            db.add(_make_report(tmp_path, "orgreport", "orgjob", handle="@tenant",
                                org_id="org_other"))
            db.commit()
        client = TestClient(main.app)
        html = client.get("/library").text
        assert "pubreport" in html or "@public" in html
        assert "@tenant" not in html
        listed = client.get("/api/reports").json()
        assert [row["id"] for row in listed] == ["pubreport"]
        assert client.get("/api/jobs/orgjob").status_code == 404
        assert client.get("/api/jobs/pubjob").status_code == 200
    finally:
        _restore(state)


def test_signup_and_billing_redirect_home():
    client = TestClient(main.app)
    assert client.get("/signup", follow_redirects=False).status_code == 303
    assert client.post("/signup", data={"name": "A", "email": "a@b.co"},
                       follow_redirects=False).status_code == 303
    assert client.get("/billing", follow_redirects=False).status_code == 303
    assert client.post("/login", data={"key": "anything"},
                       follow_redirects=False).status_code == 303
    assert client.post("/login", data={"key": "anything"},
                       follow_redirects=False).headers.get("location") == "/"


def test_mailer_skips_without_smtp(tmp_path):
    from app import mailer
    mailer.outbox.clear()
    html = tmp_path / "r.html"
    html.write_text("<html>ok</html>", encoding="utf-8")
    rep = Report(id="r", job_id="j", share_slug="slug-r", subject_name="Acme",
                 subject_handle="acme", seed_url="u", html_path=str(html),
                 payload_json='{"k":1,"desk":{"one_liner":"Acme ships tools.","job":"Name an offer."}}')
    old = settings.smtp_host
    settings.smtp_host = ""
    try:
        assert mailer.normalize_email(" Ada@Firm.COM ") == "ada@firm.com"
        assert mailer.normalize_email("not-an-email") == ""
        assert mailer.send_report("Ada@Firm.COM", rep) == "skipped"
        assert mailer.outbox[-1]["to"] == "ada@firm.com"
        assert "slug-r.html" in mailer.outbox[-1]["files"]
        text, html_body = mailer.compose_bodies(rep)
        assert "Acme ships tools." in text
        assert "Name an offer." in text
        assert "Acme ships tools." in html_body
        assert mailer._use_ssl(465) is True
        assert mailer._use_ssl(587) is False
    finally:
        settings.smtp_host = old


def test_wipe_identities_deletes_accounts_and_reports(tmp_path):
    engine, state = _isolated(tmp_path)
    try:
        with Session(engine) as db:
            db.add(Org(id="org1", name="Owner", email="owner@example.com"))
            db.add(LicenseKey(key="CI-AAAA-AAAA-AAAA-AAAA", org_id="org1"))
            db.add(Job(id="job", seed_url="u", raw_json='{"x":1}'))
            db.add(_make_report(tmp_path, "rep", "job", org_id="org1"))
            db.commit()
        from tools import housekeeping
        housekeeping.wipe_identities(engine)
        with Session(engine) as db:
            assert db.get(Org, "org1") is None
            assert db.get(LicenseKey, "CI-AAAA-AAAA-AAAA-AAAA") is None
            assert db.get(Job, "job") is None
            assert db.get(Report, "rep") is None
    finally:
        _restore(state)


def test_finalise_records_recipient_email(tmp_path):
    from app import mailer
    mailer.outbox.clear()
    engine, state = _isolated(tmp_path)
    try:
        with Session(engine) as db:
            db.add(Job(id="mailjob", seed_url=fixtures.sunil_panda().seed_url,
                       recipient_email="user@example.com", email_status="pending"))
            db.commit()
        asyncio.run(main._finalise("mailjob", [fixtures.sunil_panda()]))
        assert any(row["to"] == "user@example.com" for row in mailer.outbox)
        with Session(engine) as db:
            job = db.get(Job, "mailjob")
            assert job.email_status in {"sent", "skipped"}
    finally:
        _restore(state)
