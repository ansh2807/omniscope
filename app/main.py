"""FastAPI app: submit a link, get a report.

Flow
  POST /api/reports          -> queues a job, returns job id
  GET  /api/jobs/{id}        -> status / progress
  (Instagram post grid)      -> optional paste after the report; never a gate
  POST /api/jobs/{id}/manual -> optional upgrade of login-walled numbers
  GET  /r/{slug}             -> the shareable HTML report (deleted after REPORT_TTL_MINUTES)
  GET  /r/{slug}.html        -> download the HTML before it expires
  GET  /r/{slug}.json        -> download JSON
  GET  /r/{slug}.docx        -> the Word version
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from tools import envfile, housekeeping

from fastapi import (BackgroundTasks, Depends, FastAPI, File, Form, HTTPException,
                     Request, UploadFile, status)
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, Response)
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlmodel import Session, select

from app.config import settings
from app.db import engine as db_engine
from app.db import get_session, init_db
from app import mailer
from app.engine import pipeline
from app.engine.collectors.instagram import MANUAL_FIELDS, merge_manual
from app.engine.render import html as html_render
from app.engine.render.docx_render import render as docx_render
from app.engine.render.docx_render import render_cohort as docx_cohort
from app.models import (Alert, Entity, EvidenceItem, Job, JobStatus, Report,
                        Shortlist, ShortlistItem, SourceDocument)
from app.omni.desk import CREATOR_NEED_GUIDE, WEB_NEED_GUIDE
from app.omni.hubs import desk_rows, filings_rows, latest_web_payloads, wellknown_rows
from app.omni.watch import run_sweep
from app.omni.search_context import (bind_serper_key, normalize_serper_key,
                                     reset_serper_key)
from app.schemas import RawProfile

_log = logging.getLogger("creatorintel")

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
templates.env.globals["app_version"] = settings.app_version
templates.env.filters["ttl_left"] = housekeeping.remaining_seconds

_BODY_OPEN = re.compile(r"(<body[^>]*>)", re.IGNORECASE)


def _fingerprint(credential: str) -> str:
    """A non-reversible actor label. Raw credential material is never stored."""
    return "key:" + hashlib.sha256(credential.encode()).hexdigest()[:10]


def _template(request: Request, name: str, **ctx):
    """Render with shared nav context."""
    key = request.cookies.get("ci_key", "")
    org = resolve_org(request)
    authed = key in settings.key_set or org is not None
    base = {
        "request": request,
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "authed": authed,
        "org": org,
        "report_ttl_minutes": int(getattr(settings, "report_ttl_minutes", 0) or 0),
        "report_ttl_label": settings.report_ttl_label,
        "public_email_mode": bool(getattr(settings, "public_email_mode", True)),
        "smtp_ready": mailer.configured(),
        "free_until_label": settings.free_until_label,
        "paid_enforced": bool(getattr(settings, "paid_enforced", False)),
    }
    base.update(ctx)
    return templates.TemplateResponse(name, base)


def _ttl_minutes() -> int:
    return int(getattr(settings, "report_ttl_minutes", 0) or 0)


def _live_reports(rows: list) -> list:
    return [r for r in rows if not housekeeping.is_expired(r.created_at)]


def _report_access(session: Session, slug: str) -> tuple[Report | None, str]:
    """live | expired | missing. Expired rows are swept immediately."""
    rep = session.exec(select(Report).where(Report.share_slug == slug)).first()
    if not rep:
        return None, "missing"
    if housekeeping.is_expired(rep.created_at):
        housekeeping.sweep(db_engine)
        return None, "expired"
    return rep, "live"


def _expired_html() -> HTMLResponse:
    html = templates.get_template("expired.html").render(
        app_name=settings.app_name, minutes=_ttl_minutes() or 5)
    return HTMLResponse(html, status_code=410)


def _inject_ttl_banner(html: str, slug: str, seconds: int) -> str:
    banner = (
        f'<div id="omni-ttl" data-left="{int(seconds)}" style="position:sticky;top:0;z-index:99999;'
        "background:#111;color:#fff;padding:12px 18px;font:14px/1.45 system-ui,sans-serif;"
        'display:flex;gap:16px;flex-wrap:wrap;align-items:center;justify-content:space-between">'
        '<span>This report is deleted in <b id="omni-ttl-left">…</b>. Download it before then.</span>'
        f'<span><a href="/r/{slug}.html" style="color:#fff;font-weight:700">Download HTML</a>'
        f' · <a href="/r/{slug}.json" style="color:#fff">JSON</a>'
        f' · <a href="/r/{slug}.docx" style="color:#fff">Word</a></span></div>'
        '<script>(function(){var n=document.getElementById("omni-ttl");'
        'var el=document.getElementById("omni-ttl-left");if(!n||!el)return;'
        'var left=parseInt(n.getAttribute("data-left"),10)||0;'
        'function pad(x){return x<10?"0"+x:""+x;}'
        'function tick(){if(left<=0){location.reload();return;}'
        'el.textContent=Math.floor(left/60)+":"+pad(left%60);left-=1;setTimeout(tick,1000);}'
        "tick();})();</script>"
    )
    if _BODY_OPEN.search(html):
        return _BODY_OPEN.sub(r"\1" + banner, html, count=1)
    return banner + html


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if "PYTEST_CURRENT_TEST" not in os.environ:
        try:
            envfile.load_into_settings()
            envfile.ensure_operator_token()
        except Exception:
            pass
    # Commercial tables and the default plan catalogue.
    try:
        from app.commercial import models as _cm  # noqa: F401  (register tables)
        from app.commercial.plans import seed as seed_plans
        from sqlmodel import SQLModel
        SQLModel.metadata.create_all(db_engine)
        seed_plans(db_engine)
    except Exception:
        pass
    ttl_task = None
    if "PYTEST_CURRENT_TEST" not in os.environ:
        async def _ttl_loop() -> None:
            while True:
                await asyncio.sleep(20)
                try:
                    housekeeping.sweep(db_engine)
                except Exception:
                    _log.warning("report TTL sweep failed", exc_info=True)

        ttl_task = asyncio.create_task(_ttl_loop())
        try:
            housekeeping.maybe_wipe_identities(db_engine)
        except Exception:
            _log.warning("identity wipe failed", exc_info=True)
        try:
            housekeeping.sweep(db_engine)
        except Exception:
            _log.warning("startup report TTL sweep failed", exc_info=True)
    watch_task = None
    if settings.watch_interval_minutes > 0:
        async def _watch_loop() -> None:
            while True:
                await asyncio.sleep(settings.watch_interval_minutes * 60)
                try:
                    with Session(db_engine) as s:
                        await run_sweep(s, all_tenants=True)
                except Exception:
                    _log.warning("scheduled watch sweep failed", exc_info=True)
        watch_task = asyncio.create_task(_watch_loop())
    yield
    if ttl_task is not None:
        ttl_task.cancel()
    if watch_task is not None:
        watch_task.cancel()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="OMNISCOPE intelligence API. Claims stay observed, calculated, "
                "modelled, or unavailable. OpenAPI at /openapi.json.",
    lifespan=lifespan,
)

from app.commercial.routes import admin as _admin_router  # noqa: E402
from app.commercial.routes import public as _commercial_router  # noqa: E402

app.include_router(_commercial_router)
app.include_router(_admin_router)


# ------------------------------------------------------------------ auth
def require_key(request: Request) -> str:
    """Accept either a bootstrap key from .env or a customer licence key."""
    key = (request.headers.get("x-api-key")
           or request.headers.get("x-license-key")
           or request.query_params.get("key")
           or request.cookies.get("ci_key", ""))
    if key in settings.key_set:
        return key
    # Licence keys are the customer-facing credential.
    from sqlmodel import Session as _S

    from app.commercial.entitlements import org_for_key
    if key:
        with _S(db_engine) as db:
            org, _, err = org_for_key(db, key)
            if org:
                return key
            if err and err != "No licence key supplied.":
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, err)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid key")


def require_product(request: Request) -> str:
    """Free public product, or a valid licence/bootstrap key."""
    if settings.public_email_mode and not settings.paid_enforced:
        try:
            return require_key(request)
        except HTTPException:
            return "public"
    return require_key(request)


def _same_secret(left: str, right: str) -> bool:
    """Length-safe compare. secrets.compare_digest raises when lengths differ."""
    if not left or not right:
        return False
    return secrets.compare_digest(
        hashlib.sha256(left.encode("utf-8")).digest(),
        hashlib.sha256(right.encode("utf-8")).digest(),
    )


def _cookie_secure(request: Request) -> bool:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "")
    return proto.lower() == "https"


def _operator_identity(request: Request, extra: str = "") -> str | None:
    """Admin token or bootstrap API key. Customer licence keys are excluded."""
    token = (extra or "").strip()
    admin_candidates = (
        token,
        request.headers.get("x-admin-token") or "",
        request.cookies.get("ci_admin") or "",
        request.query_params.get("token") or "",
    )
    if settings.admin_token:
        for candidate in admin_candidates:
            if _same_secret(candidate, settings.admin_token):
                return "admin"
    key_candidates = (
        token,
        request.headers.get("x-api-key") or "",
        request.cookies.get("ci_key") or "",
        request.query_params.get("key") or "",
    )
    for candidate in key_candidates:
        if candidate and any(_same_secret(candidate, key) for key in settings.key_set):
            return candidate
    return None


def require_operator(request: Request) -> str:
    """Authorize instance-wide operations without accepting customer licences.

    Bootstrap API keys remain the operator credential for the desktop/self-hosted
    workflow.  SaaS customer licence keys are intentionally excluded because settings,
    diagnostics and global purge operate across every tenant on the instance.
    """
    ident = _operator_identity(request)
    if ident:
        return ident
    raise HTTPException(status.HTTP_403_FORBIDDEN, "operator credential required")


def resolve_org(request: Request):
    """The org behind this request, if any. None means single-tenant/bootstrap mode."""
    from sqlmodel import Session as _S

    from app.commercial.entitlements import org_for_key
    key = (request.headers.get("x-api-key")
           or request.headers.get("x-license-key")
           or request.query_params.get("key")
           or request.cookies.get("ci_key", ""))
    if not key or key in settings.key_set:
        return None
    with _S(db_engine) as db:
        org, _, _ = org_for_key(db, key)
        return org


def _gate_job(request: Request, job: Job) -> None:
    if not settings.public_email_mode:
        require_product(request)
    _assert_job_access(request, job)


def _assert_job_access(request: Request, job: Job) -> None:
    """Keep customer jobs tenant-scoped while preserving bootstrap/admin mode."""
    org = resolve_org(request)
    if org is not None and job.org_id != org.id:
        # A 404 avoids confirming that another customer's job identifier exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if org is None and job.org_id is not None and not _operator_identity(request):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")


def _assert_report_access(request: Request, report: Report) -> None:
    """Prevent a licence holder from mutating another tenant's report."""
    org = resolve_org(request)
    if org is not None and report.org_id != org.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")
    if org is None and report.org_id is not None and not _operator_identity(request):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report not found")


def check_quota(request: Request, seeds: int = 1):
    """Blocks a run the plan does not allow. Returns (org, entitlement) or (None, None)."""
    from sqlmodel import Session as _S

    from app.commercial import entitlements as ent_lib
    org = resolve_org(request)
    if not getattr(settings, "paid_enforced", False):
        return org, None
    if org is None:
        return None, None
    with _S(db_engine) as db:
        org = db.get(type(org), org.id)
        ent = ent_lib.resolve(db, org)
        if not ent.allowed:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, ent.reason)
        if seeds > ent.max_cohort_size:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                f"The {ent.plan.name} plan allows cohorts of up to "
                f"{ent.max_cohort_size} creators; you asked for {seeds}.")
        return org, ent


class CreateReport(BaseModel):
    url: str | None = None
    urls: list[str] | None = None
    input: str | None = None
    run_dorks: bool = True
    with_competitors: bool = False

    def seeds(self) -> list[str]:
        out = list(self.urls or [])
        if self.url:
            out.insert(0, self.url)
        if self.input:
            out.insert(0, self.input.strip())
        return [u.strip() for u in out if u and u.strip()]


# ------------------------------------------------------------------ worker
def _set(job_id: str, **fields) -> None:
    with Session(db_engine) as s:
        job = s.get(Job, job_id)
        if not job:
            return
        for k, v in fields.items():
            setattr(job, k, v)
        job.updated_at = datetime.utcnow()
        s.add(job)
        s.commit()


async def _run_collection(job_id: str, seeds: list[str], run_dorks: bool,
                          with_competitors: bool = False,
                          search_key: str = "") -> None:
    def progress(stage: str, pct: int) -> None:
        _set(job_id, stage=stage, progress=pct)

    token = bind_serper_key(search_key)
    try:
        await _run_collection_body(job_id, seeds, run_dorks, with_competitors,
                                   progress)
    finally:
        reset_serper_key(token)


async def _run_collection_body(job_id: str, seeds: list[str], run_dorks: bool,
                               with_competitors: bool, progress) -> None:
    try:
        _set(job_id, status=JobStatus.RUNNING.value, stage="planning", progress=1)

        # Universal input: NEXUS decides which engine runs. Creator seeds take the
        # existing pipeline below; websites and keywords take the web engine.
        from app.omni.input_resolver import KIND_CREATOR, KIND_POST, classify
        kinds = []
        for seed in seeds:
            try:
                kinds.append(classify(seed).kind)
            except ValueError:
                kinds.append(KIND_CREATOR)
        if any(k == KIND_POST for k in kinds):
            if len(seeds) > 1:
                raise RuntimeError(
                    "Post and video URLs run as individual investigations.")
            await _run_media_analysis(job_id, seeds[0])
            return
        if any(k != KIND_CREATOR for k in kinds):
            if len(seeds) > 1:
                raise RuntimeError(
                    "Cohort reports compare creators. Websites and keywords run as "
                    "individual investigations — submit them one at a time.")
            await _run_web_analysis(job_id, seeds[0])
            return

        _set(job_id, stage="starting", progress=2)
        raws = []
        for i, seed in enumerate(seeds):
            def sub(stage: str, pct: int, _i=i) -> None:
                progress(f"[{_i + 1}/{len(seeds)}] {stage}",
                         int((_i + pct / 100) / len(seeds) * 80) + 2)
            raws.append(await pipeline.collect(seed, run_dorks=run_dorks, progress=sub))

        _set(job_id, raw_json=json.dumps([r.model_dump_json() for r in raws]))

        # A missing Instagram follower count stays unavailable. Public profiles
        # often serve a login wall to datacenter crawlers; nobody has to type it.
        await _finalise(job_id, raws, with_competitors=with_competitors)
    except Exception as exc:  # noqa: BLE001
        _log.warning("job %s failed", job_id, exc_info=True)
        _set(job_id, status=JobStatus.FAILED.value, error=str(exc)[:400])


async def _run_web_analysis(job_id: str, seed: str) -> None:
    """Website/keyword investigation: NEXUS web plan -> scored report."""
    from app.omni import nexus

    def progress(stage: str, pct: int) -> None:
        _set(job_id, stage=stage, progress=pct)

    payload = await nexus.run_web(seed, uuid.uuid4().hex[:12], progress=progress)

    _set(job_id, stage="rendering", progress=95)
    with Session(db_engine) as s:
        existing = s.exec(select(Report).where(Report.job_id == job_id)).first()
        job = s.get(Job, job_id)
        org_id = job.org_id if job else None
        try:
            from app.omni.graph import load_history
            from app.omni.oracle import forecast
            history = load_history(s, payload.domain, org_id)
            payload.prediction = forecast(
                current_score=payload.overall_score,
                current_tech=[t.name for t in payload.tech],
                current_socials=[x.platform for x in payload.socials if not x.error],
                latest_dated=(payload.content or {}).get("latest_dated_content"),
                history=history,
            ).model_dump()
            from app.omni.trends import from_history
            payload.trend_intel = from_history(payload.overall_score, history).model_dump()
        except Exception:
            _log.warning("ORACLE forecast failed for %s", job_id, exc_info=True)
    report_id = existing.id if existing else payload.report_id
    is_new_report = existing is None
    out = Path(settings.reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / f"{report_id}.html"
    html_path.write_text(html_render.render_web(payload), encoding="utf-8")

    slug = existing.share_slug if existing else f"{_slugify(payload.entity_name)}-{report_id[:6]}"
    summary = {
        "overall_score": payload.overall_score,
        "domain": payload.domain,
        "dimensions": {d.key: d.score for d in payload.scores},
        "tech": [t.name for t in payload.tech][:10],
        "social_accounts": len([x for x in payload.socials if not x.error]),
    }
    with Session(db_engine) as s:
        report = s.get(Report, report_id)
        if report is None:
            report = Report(id=report_id, job_id=job_id, share_slug=slug,
                            org_id=org_id, subject_name=payload.entity_name,
                            subject_handle=payload.domain, seed_url=seed,
                            html_path=str(html_path))
        report.subject_name = payload.entity_name
        report.subject_handle = payload.domain
        report.seed_url = seed
        report.kind = "web"
        report.subject_count = 1
        report.subjects_json = json.dumps([{
            "name": payload.entity_name, "handle": payload.domain, "seed_url": seed}])
        report.html_path = str(html_path)
        report.docx_path = None
        report.payload_json = payload.model_dump_json()
        report.summary_json = json.dumps(summary)
        report.overall_confidence = round(payload.overall_score / 100, 3)
        s.add(report)
        s.commit()
        try:
            from app.omni.graph import upsert_from_web
            upsert_from_web(s, payload, org_id=org_id, report_id=report_id)
        except Exception:
            _log.warning("entity graph upsert failed for %s", report_id, exc_info=True)

    if org_id and is_new_report:
        try:
            from app.commercial import entitlements as _ent
            from app.commercial.models import Org as _Org
            with Session(db_engine) as s:
                org = s.get(_Org, org_id)
                if org:
                    _ent.consume(s, org, creators=1)
        except Exception:
            pass

    _set(job_id, status=JobStatus.DONE.value, stage="done", progress=100)
    _after_report_ready(job_id)


async def _run_media_analysis(job_id: str, seed: str) -> None:
    """Post/video: public metadata only."""
    from app.omni.media import analyse as analyse_media

    def progress(stage: str, pct: int) -> None:
        _set(job_id, stage=stage, progress=pct)

    progress("fetching public page", 20)
    payload = await analyse_media(seed, uuid.uuid4().hex[:12])
    progress("rendering", 90)
    with Session(db_engine) as s:
        existing = s.exec(select(Report).where(Report.job_id == job_id)).first()
        job = s.get(Job, job_id)
        org_id = job.org_id if job else None
    report_id = existing.id if existing else payload.report_id
    is_new_report = existing is None
    out = Path(settings.reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / f"{report_id}.html"
    html_path.write_text(html_render.render_media(payload), encoding="utf-8")
    name = payload.title or payload.platform or "media"
    slug = existing.share_slug if existing else f"{_slugify(name)}-{report_id[:6]}"
    with Session(db_engine) as s:
        report = s.get(Report, report_id)
        if report is None:
            report = Report(id=report_id, job_id=job_id, share_slug=slug,
                            org_id=org_id, subject_name=name,
                            subject_handle=payload.platform, seed_url=seed,
                            html_path=str(html_path))
        report.subject_name = name
        report.subject_handle = payload.platform
        report.seed_url = seed
        report.kind = "media"
        report.subject_count = 1
        report.subjects_json = json.dumps([{
            "name": name, "handle": payload.platform, "seed_url": seed}])
        report.html_path = str(html_path)
        report.docx_path = None
        report.payload_json = payload.model_dump_json()
        report.summary_json = json.dumps({
            "platform": payload.platform, "assessed": payload.assessed,
            "method": payload.method})
        report.overall_confidence = 0.9 if payload.assessed else 0.0
        s.add(report)
        s.commit()
    if org_id and is_new_report:
        try:
            from app.commercial import entitlements as _ent
            from app.commercial.models import Org as _Org
            with Session(db_engine) as s:
                org = s.get(_Org, org_id)
                if org:
                    _ent.consume(s, org, creators=1)
        except Exception:
            pass
    _set(job_id, status=JobStatus.DONE.value, stage="done", progress=100)
    _after_report_ready(job_id)


def _load_raws(job: Job) -> list[RawProfile]:
    if not job.raw_json:
        return []
    data = json.loads(job.raw_json)
    if isinstance(data, list):
        return [RawProfile.model_validate_json(d) for d in data]
    return [RawProfile.model_validate(data)]


async def _finalise(job_id: str, raws: list[RawProfile],
                    with_competitors: bool = False) -> None:
    _set(job_id, status=JobStatus.RUNNING.value, stage="analysing", progress=88)
    payloads = []
    for raw in raws:
        comps = await pipeline.find_competitors(raw) if with_competitors else None
        payloads.append(pipeline.analyse(raw, uuid.uuid4().hex[:12], competitors=comps))

    _set(job_id, stage="rendering", progress=95)
    with Session(db_engine) as s:
        existing = s.exec(select(Report).where(Report.job_id == job_id)).first()
        job = s.get(Job, job_id)
        org_id = job.org_id if job else None
        report_id = existing.id if existing else uuid.uuid4().hex[:12]
        existing_slug = existing.share_slug if existing else None
    is_new_report = existing is None
    out = Path(settings.reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / f"{report_id}.html"
    docx_path = out / f"{report_id}.docx"

    fit_score = None
    media_verdict = None
    summary: dict = {}
    if len(payloads) == 1:
        payload = payloads[0]
        html_path.write_text(html_render.render(payload), encoding="utf-8")
        try:
            docx_render(payload, str(docx_path))
        except Exception:
            docx_path = None
        name, handle, seed = payload.subject_name, payload.subject_handle, payload.seed_url
        conf, kind = payload.audience.overall_confidence, "single"
        blob = payload.model_dump_json()
        mb = payload.media_buy or {}
        fit_score = mb.get("fit_score")
        media_verdict = mb.get("verdict")
        ag = payload.agency or {}
        summary = {
            "fit_score": fit_score, "media_verdict": media_verdict,
            "media_label": mb.get("label"),
            "influence": ((ag.get("influence_score") or {}).get("value") or {}).get("score"),
            "reach": ((ag.get("estimated_reach") or {}).get("value") or {}).get("per_placement_range"),
            "platforms": [a.platform for a in payload.raw.accounts
                          if a.raw.get("analysis_eligible") is not False][:8],
        }
    else:
        cp = pipeline.analyse_cohort(payloads, report_id)
        html_path.write_text(html_render.render_cohort(cp), encoding="utf-8")
        try:
            docx_cohort(cp, str(docx_path))
        except Exception:
            docx_path = None
        name = " · ".join(p.subject_name for p in payloads[:3]) + (
            f" +{len(payloads) - 3}" if len(payloads) > 3 else "")
        handle = f"{len(payloads)} creators"
        seed = payloads[0].seed_url
        conf = sum(p.audience.overall_confidence for p in payloads) / len(payloads)
        kind = "cohort"
        blob = cp.model_dump_json()
        fits = [p.media_buy.get("fit_score") for p in payloads
                if p.media_buy and p.media_buy.get("fit_score") is not None]
        fit_score = round(sum(fits) / len(fits), 1) if fits else None
        media_verdict = "cohort"
        summary = {"fit_score": fit_score, "media_verdict": media_verdict,
                   "creators": [p.subject_name for p in payloads]}

    slug = existing_slug or f"{_slugify(name)}-{report_id[:6]}"
    subjects = [{"name": p.subject_name, "handle": p.subject_handle,
                 "seed_url": p.seed_url} for p in payloads]
    with Session(db_engine) as s:
        report = s.get(Report, report_id)
        if report is None:
            report = Report(id=report_id, job_id=job_id, share_slug=slug,
                            org_id=org_id, subject_name=name, subject_handle=handle,
                            seed_url=seed, html_path=str(html_path))
        report.subject_name = name
        report.subject_handle = handle
        report.seed_url = seed
        report.kind = kind
        report.subject_count = len(payloads)
        report.subjects_json = json.dumps(subjects)
        report.html_path = str(html_path)
        report.docx_path = str(docx_path) if docx_path else None
        report.payload_json = blob
        report.summary_json = json.dumps(summary)
        report.overall_confidence = round(conf, 3)
        report.fit_score = fit_score
        report.media_verdict = media_verdict
        s.add(report)
        s.commit()
        if kind == "single" and payloads:
            try:
                from app.omni.graph import upsert_from_creator
                from app.omni.resolve import surface_from_report
                upsert_from_creator(
                    s, surface_from_report(payloads[0]),
                    org_id=org_id, report_id=report_id)
            except Exception:
                _log.warning("creator graph upsert failed for %s", report_id,
                             exc_info=True)
    # Regenerating a report after optional analyst enrichment is not a new billable run.
    if org_id and is_new_report:
        try:
            from app.commercial import entitlements as _ent
            from app.commercial.models import Org as _Org
            with Session(db_engine) as s:
                org = s.get(_Org, org_id)
                if org:
                    _ent.consume(s, org, creators=len(payloads))
        except Exception:
            pass

    _set(job_id, status=JobStatus.DONE.value, stage="done", progress=100)
    _after_report_ready(job_id)


def _after_report_ready(job_id: str) -> None:
    """Email the recipient, then prune expired reports."""
    with Session(db_engine) as s:
        job = s.get(Job, job_id)
        report = s.exec(select(Report).where(Report.job_id == job_id)).first()
        to = (job.recipient_email if job else None) or ""
    status = "skipped"
    if report is not None and to:
        status = mailer.send_report(to, report)
    with Session(db_engine) as s:
        job = s.get(Job, job_id)
        if job is not None:
            job.email_status = status
            s.add(job)
            s.commit()
    try:
        housekeeping.sweep(db_engine)
    except Exception:
        _log.warning("housekeeping sweep failed; storage limits not enforced this run",
                     exc_info=True)


def _slugify(s: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in (s or "report")]
    out = "".join(keep)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:48] or "report"


# ------------------------------------------------------------------ API
@app.post("/api/reports")
async def create_report(request: Request, body: CreateReport, bg: BackgroundTasks,
                        key: str = Depends(require_product)):
    seeds = body.seeds()
    if not seeds:
        raise HTTPException(422, "provide `url` or `urls`")
    if len(seeds) > 8:
        raise HTTPException(422, "maximum 8 creators per cohort report")
    org, _ent = check_quota(request, len(seeds))
    job_id = uuid.uuid4().hex[:12]
    with Session(db_engine) as s:
        s.add(Job(id=job_id, seed_url=seeds[0], seeds_json=json.dumps(seeds),
                  created_by=_fingerprint(key), org_id=org.id if org else None))
        s.commit()
    bg.add_task(asyncio.run,
                _run_collection(job_id, seeds, body.run_dorks, body.with_competitors))
    from app.omni.input_resolver import classify
    from app.omni.nexus import plan as plan_input
    try:
        ui = classify(seeds[0])
        planned = plan_input(ui)
        input_kind, engines = ui.kind, [s.engine for s in planned.steps]
    except Exception:
        input_kind, engines = "unknown", []
    report_kind = ("cohort" if len(seeds) > 1 else
                   "single" if input_kind == "creator" else
                   "media" if input_kind == "post" else "web")
    return {"job_id": job_id, "status": "queued", "seeds": len(seeds),
            "kind": report_kind, "input_kind": input_kind, "engines": engines,
            "poll": f"{settings.public_base_url}/api/jobs/{job_id}"}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, request: Request, session: Session = Depends(get_session),
               key: str = Depends(require_product)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    _assert_job_access(request, job)
    body = {"job_id": job.id, "status": job.status, "stage": job.stage,
            "progress": job.progress, "error": job.error}
    rep = session.exec(select(Report).where(Report.job_id == job_id)).first()
    if rep:
        body["report"] = {
            "id": rep.id, "slug": rep.share_slug,
            "html": f"{settings.public_base_url}/r/{rep.share_slug}",
            "docx": f"{settings.public_base_url}/r/{rep.share_slug}.docx",
            "confidence": rep.overall_confidence,
        }
    if job.status == JobStatus.NEEDS_INPUT.value:
        body["manual_form"] = f"{settings.public_base_url}/jobs/{job_id}/manual"
        body["manual_fields"] = MANUAL_FIELDS
    return body


@app.post("/api/jobs/{job_id}/manual")
async def submit_manual(job_id: str, payload: dict, request: Request,
                        key: str = Depends(require_product)):
    with Session(db_engine) as s:
        job = s.get(Job, job_id)
        if not job or not job.raw_json:
            raise HTTPException(404, "job not found or not collected yet")
        _assert_job_access(request, job)
        raws = _load_raws(job)
    for raw in raws:
        for acc in raw.accounts:
            if acc.platform == "instagram":
                merge_manual(acc, payload)
    _set(job_id, manual_json=json.dumps(payload),
         raw_json=json.dumps([r.model_dump_json() for r in raws]))
    await _finalise(job_id, raws)
    with Session(db_engine) as s:
        rep = s.exec(select(Report).where(Report.job_id == job_id)).first()
    return {"status": "done",
            "report": f"{settings.public_base_url}/r/{rep.share_slug}" if rep else None}


@app.get("/api/reports")
def list_reports(request: Request, session: Session = Depends(get_session),
                 key: str = Depends(require_product)):
    query = select(Report)
    org = resolve_org(request)
    if org is not None:
        query = query.where(Report.org_id == org.id)
    else:
        query = query.where(Report.org_id == None)  # noqa: E711
    rows = session.exec(query.order_by(Report.created_at.desc()).limit(100)).all()
    return [{"id": r.id, "name": r.subject_name, "handle": r.subject_handle,
             "slug": r.share_slug, "kind": r.kind, "subjects": r.subject_count,
             "confidence": r.overall_confidence,
             "created_at": r.created_at.isoformat()} for r in _live_reports(rows)]


# ------------------------------------------------------------------ share links
@app.get("/r/{slug}.html")
def download_report_html(slug: str, session: Session = Depends(get_session)):
    rep, state = _report_access(session, slug)
    if state == "expired":
        raise HTTPException(410, "This report expired and was deleted")
    if not rep or not Path(rep.html_path).exists():
        raise HTTPException(404, "report not found")
    return FileResponse(rep.html_path, filename=f"{slug}.html", media_type="text/html")


@app.get("/r/{slug}.json")
def download_report_json(slug: str, session: Session = Depends(get_session)):
    from app.omni.export import pack_report
    rep, state = _report_access(session, slug)
    if state == "expired":
        raise HTTPException(410, "This report expired and was deleted")
    pack = pack_report(rep)
    if not pack:
        raise HTTPException(404, "JSON payload was not stored for this report")
    return JSONResponse(
        pack,
        headers={"Content-Disposition": f'attachment; filename="{slug}.json"'},
    )


@app.get("/r/{slug}.docx")
def download_docx(slug: str, session: Session = Depends(get_session)):
    rep, state = _report_access(session, slug)
    if state == "expired":
        raise HTTPException(410, "This report expired and was deleted")
    if not rep or not rep.docx_path or not Path(rep.docx_path).exists():
        raise HTTPException(404, "docx not available")
    return FileResponse(rep.docx_path, filename=f"{slug}.docx",
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.get("/r/{slug}", response_class=HTMLResponse)
def view_report(slug: str, session: Session = Depends(get_session)):
    rep, state = _report_access(session, slug)
    if state == "expired":
        return _expired_html()
    if not rep or not Path(rep.html_path).exists():
        raise HTTPException(404, "report not found")
    html = Path(rep.html_path).read_text(encoding="utf-8")
    left = housekeeping.remaining_seconds(rep.created_at)
    if left is not None:
        html = _inject_ttl_banner(html, slug, left)
    return HTMLResponse(html)


# ------------------------------------------------------------------ web UI
@app.get("/", response_class=HTMLResponse)
def home(request: Request, key: str | None = None,
         session: Session = Depends(get_session)):
    # One-click launch: the desktop launcher opens /?key=... . Accept it once, store it
    # in an httpOnly cookie, then redirect to a clean URL so the key is not left in the
    # address bar or in browser history.
    if key:
        accepted = key in settings.key_set
        if not accepted:
            from sqlmodel import Session as _S

            from app.commercial.entitlements import org_for_key
            with _S(db_engine) as _db:
                _org, _, _ = org_for_key(_db, key.strip().upper())
                if _org:
                    accepted, key = True, key.strip().upper()
        if accepted:
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie("ci_key", key, httponly=True, samesite="lax",
                            max_age=60 * 60 * 24 * 30)
            return resp
    key = request.cookies.get("ci_key", "")
    org = resolve_org(request)
    reports, ent = [], None
    authed = key in settings.key_set or org is not None
    if authed and not settings.public_email_mode:
        q = select(Report).order_by(Report.created_at.desc()).limit(25)
        if org:
            q = select(Report).where(Report.org_id == org.id).order_by(
                Report.created_at.desc()).limit(25)
        reports = _live_reports(list(session.exec(q).all()))
        if org:
            from app.commercial import entitlements as _ent
            ent = _ent.resolve(session, org)
    remembered = mailer.normalize_email(request.cookies.get("ci_email", ""))
    err = request.query_params.get("err", "")
    return _template(request, "index.html",
                     reports=reports, status=_source_status(), ent=ent,
                     remembered_email=remembered,
                     form_error=("email" if err == "email"
                                 else "key" if err == "key"
                                 else "url" if err == "1" else ""),
                     hide_setup=True)


@app.post("/dismiss-setup")
def dismiss_setup(request: Request):
    """Optional means optional — stop showing the setup card."""
    require_product(request)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("ci_setup_dismissed", "1", httponly=True, samesite="lax",
                    max_age=60 * 60 * 24 * 365)
    return resp


@app.post("/login")
def login(key: str = Form(...)):
    if settings.public_email_mode:
        return RedirectResponse("/", status_code=303)
    ok = key in settings.key_set
    if not ok:
        from sqlmodel import Session as _S

        from app.commercial.entitlements import org_for_key
        with _S(db_engine) as db:
            org, _, _ = org_for_key(db, key.strip().upper())
            ok = org is not None
            if ok:
                key = key.strip().upper()
    if not ok:
        return RedirectResponse("/?err=1", status_code=303)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("ci_key", key, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return resp


@app.post("/generate")
async def generate(request: Request, bg: BackgroundTasks, url: str = Form(...),
                   email: str = Form(default=""),
                   with_competitors: str = Form(default=""),
                   search_mode: str = Form(default="free"),
                   serper_key: str = Form(default="")):
    addr = mailer.normalize_email(email)
    if not settings.public_email_mode:
        require_product(request)
    seeds = [u.strip() for u in url.replace(",", "\n").splitlines() if u.strip()][:8]
    if not seeds:
        return RedirectResponse("/?err=1", status_code=303)
    guest_key = ""
    if (search_mode or "").strip().lower() == "serper":
        guest_key = normalize_serper_key(serper_key)
        if not guest_key:
            return RedirectResponse("/?err=key", status_code=303)
    org = None
    if not settings.public_email_mode:
        try:
            org, _ent = check_quota(request, len(seeds))
        except HTTPException as exc:
            return templates.TemplateResponse("blocked.html", {
                "request": request, "app_name": settings.app_name,
                "reason": exc.detail}, status_code=402)
    job_id = uuid.uuid4().hex[:12]
    with Session(db_engine) as s:
        s.add(Job(id=job_id, seed_url=seeds[0], seeds_json=json.dumps(seeds),
                  org_id=org.id if org else None,
                  recipient_email=addr or None,
                  email_status="pending" if addr else None))
        s.commit()
    bg.add_task(asyncio.run,
                _run_collection(job_id, seeds, True, bool(with_competitors),
                                guest_key))
    resp = RedirectResponse(f"/jobs/{job_id}", status_code=303)
    if addr:
        resp.set_cookie("ci_email", addr, samesite="lax", max_age=60 * 60 * 24 * 180)
    return resp


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(job_id: str, request: Request, session: Session = Depends(get_session)):
    if not settings.public_email_mode:
        require_product(request)
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    _assert_job_access(request, job)
    rep = session.exec(select(Report).where(Report.job_id == job_id)).first()
    can_enrich, already = False, bool(job.manual_json)
    if job.raw_json:
        try:
            can_enrich = any(a.platform == "instagram" and a.needs_manual
                             for r in _load_raws(job) for a in r.accounts)
        except Exception:
            can_enrich = False
    ttl_seconds = housekeeping.remaining_seconds(rep.created_at) if rep else None
    return _template(request, "job.html", job=job, report=rep, fields=MANUAL_FIELDS,
                     can_enrich=can_enrich, already_enriched=already,
                     ttl_seconds=ttl_seconds)


@app.get("/jobs/{job_id}/manual", response_class=HTMLResponse)
def manual_page(job_id: str, request: Request, session: Session = Depends(get_session)):
    if not settings.public_email_mode:
        require_product(request)
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404)
    _assert_job_access(request, job)
    from app.engine.collectors import browser as _br
    reason, blocking = "Optional enrichment.", False
    try:
        accs = [a for r in _load_raws(job) for a in r.accounts if a.platform == "instagram"]
    except Exception:
        accs = []
    got = next((a for a in accs if a.followers), None)
    if any(a.followers is None for a in accs):
        reason = ("Instagram did not print a follower count. Leave it blank — the report "
                  "marks that field unavailable rather than guessing. Reel views, likes, "
                  "comments and audience demographics stay behind the sign-in wall.")
    elif got:
        reason = (f"Nothing here is required. The engine already read "
                  f"{got.followers:,} followers"
                  + (f", {got.posts:,} posts" if got.posts else "")
                  + (", the bio" if got.bio else "")
                  + (f" and {len(got.highlights)} highlight names" if got.highlights else "")
                  + ". What stays behind Instagram's sign-in wall is post-level performance "
                    "— reel views, likes, comments and audience demographics. Fill any of "
                    "it to upgrade those fields from estimated to observed, or skip it "
                    "entirely.")
    return _template(request, "manual.html", job=job, fields=MANUAL_FIELDS,
                     reason=reason, blocking=blocking,
                     browser_on=_br.enabled(), browser_hint=_br.INSTALL_HINT)


@app.post("/jobs/{job_id}/skip")
async def manual_skip(job_id: str, request: Request):
    """Generate the report now, without any analyst input."""
    with Session(db_engine) as s:
        job = s.get(Job, job_id)
        if not job or not job.raw_json:
            raise HTTPException(404)
        _gate_job(request, job)
        if job.status == JobStatus.DONE.value:
            return RedirectResponse(f"/jobs/{job_id}", status_code=303)
        raws = _load_raws(job)
    await _finalise(job_id, raws)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.post("/jobs/{job_id}/manual")
async def manual_submit(job_id: str, request: Request):
    form = dict(await request.form())
    with Session(db_engine) as s:
        job = s.get(Job, job_id)
        if not job or not job.raw_json:
            raise HTTPException(404)
        _gate_job(request, job)
        raws = _load_raws(job)
    for raw in raws:
        for acc in raw.accounts:
            if acc.platform == "instagram":
                merge_manual(acc, form)
    _set(job_id, manual_json=json.dumps(form),
         raw_json=json.dumps([r.model_dump_json() for r in raws]))
    await _finalise(job_id, raws)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


# ------------------------------------------------------------------ settings
def _source_status() -> dict:
    from app.engine.collectors import browser as br
    return {
        "keyless": {
            "on": True, "installed": True,
            "label": "Keyless discovery",
            "why": ("Apple Podcasts, Wikipedia and autocomplete — official public APIs "
                    "that need no key. Always on."),
            "fix": "",
        },
        "browser": {
            "on": br.enabled(),
            "installed": br.available(),
            "mode": settings.browser_mode,
            "label": "Browser tier",
            "why": ("Reads Instagram follower counts, YouTube all-time view counts and "
                    "YouTube comments with no API key, logged out."),
            "fix": ("Run ENABLE-BROWSER.bat, or restart with START.bat which installs it "
                    "automatically."),
        },
        "youtube": {
            "on": bool(settings.youtube_api_key), "installed": True,
            "label": "YouTube Data API",
            "why": ("Optional once the browser tier is on. Gives exact view counts and "
                    "real publish dates instead of rounded figures."),
            "fix": "Google Cloud Console → enable YouTube Data API v3 → create an API key.",
        },
        "search": {
            "on": settings.search_provider not in ("", "none"), "installed": True,
            "label": "Search / discovery",
            "why": ("Optional. Adds competitor discovery, page-one search ownership, and "
                    "press and news mentions. Podcasts, Wikipedia, related searches and "
                    "cross-platform discovery already work without it."),
            "fix": "serper.dev gives 2,500 free queries — roughly 250 reports.",
        },
    }


def _settings_denied_copy() -> str:
    if not settings.admin_token and not settings.key_set:
        return ("No operator token is loaded. On the server read "
                "/srv/data/.operator-token inside the app container, then paste it here.")
    return "Operator token is required to save keys or clear stored data."


def _settings_html(request: Request, *, saved: str | None = None,
                   purged: str | None = None, jobs: str | None = None,
                   form_error: str | None = None):
    ident = _operator_identity(request)
    return _template(
        request, "settings.html",
        env=envfile.read() if ident else {},
        status=_source_status(),
        saved=saved,
        usage=housekeeping.disk_usage(),
        purged=purged,
        jobs=jobs,
        form_error=form_error,
        operator_ok=bool(ident),
        retention_days=settings.retention_days,
        max_reports=settings.max_reports,
    )


def _attach_operator_cookie(response: RedirectResponse, request: Request) -> RedirectResponse:
    if settings.admin_token:
        response.set_cookie(
            "ci_admin",
            settings.admin_token,
            httponly=True,
            samesite="lax",
            secure=_cookie_secure(request),
            max_age=60 * 60 * 24 * 30,
            path="/",
        )
    return response


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str | None = None, purged: str | None = None,
                  jobs: str | None = None):
    return _settings_html(request, saved=saved, purged=purged, jobs=jobs)


@app.post("/settings/purge")
async def settings_purge(request: Request):
    """Delete every stored report, its collected source data and the HTTP cache."""
    form = dict(await request.form())
    operator = _operator_identity(request, extra=str(form.get("operator_token") or ""))
    if not operator:
        return _settings_html(request, form_error=_settings_denied_copy())
    s = housekeeping.purge_all(db_engine)
    try:
        from app.commercial.entitlements import audit
        with Session(db_engine) as db:
            audit(db,
                  actor="admin" if operator == "admin" else _fingerprint(operator),
                  action="settings.purge",
                  detail=f"reports={s.reports_deleted} jobs={s.jobs_deleted} "
                         f"files={s.files_deleted} cache_files={s.cache_files_deleted}")
    except Exception:
        _log.warning("purge completed but writing the audit row failed", exc_info=True)
    return _attach_operator_cookie(RedirectResponse(
        f"/settings?purged={s.reports_deleted}&jobs={s.jobs_deleted}", status_code=303),
        request)


@app.post("/reports/{report_id}/delete")
def delete_report(request: Request, report_id: str):
    key = require_key(request)
    with Session(db_engine) as session:
        report = session.get(Report, report_id)
        if not report:
            raise HTTPException(404, "report not found")
        _assert_report_access(request, report)
        subject = report.subject_name
    from tools import housekeeping
    housekeeping.delete_one(db_engine, report_id)
    try:
        from app.commercial.entitlements import audit
        with Session(db_engine) as db:
            audit(db, actor=_fingerprint(key), action="report.delete",
                  target=report_id, detail=subject)
    except Exception:
        _log.warning("report %s deleted but writing the audit row failed", report_id,
                     exc_info=True)
    return RedirectResponse("/", status_code=303)


@app.post("/settings")
async def settings_save(request: Request):
    form = dict(await request.form())
    if not _operator_identity(request, extra=str(form.get("operator_token") or "")):
        return _settings_html(request, form_error=_settings_denied_copy())
    updates = {
        k: str(v).strip()
        for k, v in form.items()
        if k in envfile.ALLOWED and k != "ADMIN_TOKEN" and str(v).strip()
    }
    # Choosing a provider without a key would silently do nothing; infer it instead.
    if updates.get("SERPER_API_KEY"):
        updates["SEARCH_PROVIDER"] = "serper"
    elif updates.get("BRAVE_API_KEY"):
        updates["SEARCH_PROVIDER"] = "brave"
    elif updates.get("GOOGLE_CSE_KEY") and updates.get("GOOGLE_CSE_CX"):
        updates["SEARCH_PROVIDER"] = "google_cse"
    try:
        changed = envfile.write(updates)
        envfile.apply_to_settings(updates)
    except OSError:
        return _settings_html(
            request,
            form_error="Could not write keys to the data volume. Check that /srv/data is writable.",
        )
    return _attach_operator_cookie(
        RedirectResponse(f"/settings?saved={len(changed)}", status_code=303),
        request)


@app.get("/diagnostics", response_class=HTMLResponse)
async def diagnostics_page(request: Request):
    """Live self-test of every collection tier against real public pages."""
    require_operator(request)
    from app.omni.registry import registry
    from tools import diagnostics
    rep = await diagnostics.run()
    return _template(request, "diagnostics.html", rep=rep, providers=registry())


@app.post("/api/v1/analyze")
async def analyze_v1(request: Request, body: CreateReport, bg: BackgroundTasks,
                     key: str = Depends(require_product)):
    """Versioned Deep Analyze. Same job pipeline as POST /api/reports."""
    return await create_report(request, body, bg, key)


@app.get("/api/v1/analysis/{job_id}")
def analysis_v1(job_id: str, request: Request, session: Session = Depends(get_session),
                key: str = Depends(require_product)):
    """Spec GET /analysis/{id} — job + report pointers."""
    return job_status(job_id, request, session, key)


@app.get("/api/v1/entities/{entity_id}")
def entity_v1(entity_id: str, request: Request, session: Session = Depends(get_session),
              key: str = Depends(require_product)):
    entity = session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(404, "entity not found")
    org = resolve_org(request)
    if org is not None and entity.org_id != org.id:
        raise HTTPException(404, "entity not found")
    if org is None and entity.org_id is not None:
        raise HTTPException(404, "entity not found")
    from app.omni.graph import aliases_for, links_for
    from app.omni.timeline import brief_from_report
    report = session.get(Report, entity.last_report_id) if entity.last_report_id else None
    return {
        "id": entity.id, "kind": entity.kind, "name": entity.name,
        "domain": entity.domain, "url": entity.canonical_url,
        "score": entity.last_score, "watched": bool(entity.watched),
        "report_id": entity.last_report_id,
        "snapshot": entity.snapshot(),
        "updated_at": entity.updated_at.isoformat(),
        "aliases": [{
            "kind": a.kind, "value": a.value, "platform": a.platform,
            "method": a.method, "confidence": a.confidence,
            "source_url": a.source_url,
        } for a in aliases_for(session, entity.id)],
        "links": [{
            "rel": link.rel, "to_id": other.id, "to_name": other.name,
            "to_kind": other.kind, "confidence": link.confidence,
            "evidence": link.evidence, "method": link.method,
        } for link, other in links_for(session, entity.id)],
        "brief": brief_from_report(report),
    }


@app.get("/api/v1/entities/{entity_id}/timeline")
def entity_timeline_v1(entity_id: str, request: Request,
                       session: Session = Depends(get_session),
                       key: str = Depends(require_product)):
    entity = session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(404, "entity not found")
    org = resolve_org(request)
    if org is not None and entity.org_id != org.id:
        raise HTTPException(404, "entity not found")
    if org is None and entity.org_id is not None:
        raise HTTPException(404, "entity not found")
    from app.omni.timeline import from_stores
    report = session.get(Report, entity.last_report_id) if entity.last_report_id else None
    return [e.model_dump() for e in from_stores(session, entity.id, report=report)]


@app.get("/api/v1/timeline")
def timeline_v1(request: Request, session: Session = Depends(get_session),
                key: str = Depends(require_product)):
    from app.omni.timeline import tenant_timeline
    org = resolve_org(request)
    return [e.model_dump() for e in tenant_timeline(session, org.id if org else None)]


class ResolveBody(BaseModel):
    input: str


@app.post("/api/v1/entities/resolve")
def entities_resolve_v1(body: ResolveBody, request: Request,
                        session: Session = Depends(get_session),
                        key: str = Depends(require_product)):
    """Look up a stored entity by hard identifiers. Does not invent matches."""
    from app.omni.graph import lookup
    from app.omni.input_resolver import classify
    raw = (body.input or "").strip()
    if not raw:
        raise HTTPException(400, "input is required")
    try:
        ui = classify(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    org = resolve_org(request)
    org_id = org.id if org else None
    result = lookup(session, org_id=org_id, kind=ui.kind, value=ui.value,
                    platform=ui.platform, handle=ui.handle, domain=ui.domain)
    result["input"] = {"kind": ui.kind, "value": ui.value, "original": ui.original,
                       "notes": ui.notes}
    return result


@app.post("/api/v1/watchlists")
async def watchlists_v1(request: Request, session: Session = Depends(get_session),
                        key: str = Depends(require_product)):
    """Watch an entity. Body: {\"entity_id\": \"...\"}."""
    body = await request.json()
    entity_id = str(body.get("entity_id") or "")
    entity = session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(404, "entity not found")
    org = resolve_org(request)
    if org is not None and entity.org_id != org.id:
        raise HTTPException(404, "entity not found")
    entity.watched = True
    session.add(entity)
    session.commit()
    return {"entity_id": entity.id, "watched": True}


@app.post("/api/v1/watchlists/run")
async def watchlists_run_v1(request: Request, session: Session = Depends(get_session),
                            key: str = Depends(require_product)):
    """Homepage sweep of watched websites. Does not consume a report credit."""
    from app.omni.watch import run_sweep
    org = resolve_org(request)
    return await run_sweep(session, org.id if org else None)


@app.get("/api/v1/awards")
def awards_v1(session: Session = Depends(get_session),
              key: str = Depends(require_product)):
    from app.omni.award_dates import intel_from_row, stored_map
    from app.omni.awards import CATALOG
    freshness = stored_map(session)
    rows = []
    for award in CATALOG:
        row = freshness.get(award.name)
        intel = intel_from_row(row) if row else None
        rows.append({
            "name": award.name, "org": award.org, "season": award.season,
            "region": award.region, "category": award.category, "url": award.url,
            "typical_season": award.season,
            "official_dates": [d.model_dump() for d in intel.dates] if intel else [],
            "date_status": row.status if row else "unfetched",
            "date_reason": intel.reason if intel else "",
            "fetched_at": row.fetched_at.isoformat() if row else None,
        })
    return rows


@app.post("/api/v1/awards/refresh")
async def awards_refresh_v1(session: Session = Depends(get_session),
                            key: str = Depends(require_product)):
    from app.omni.award_dates import refresh_catalog
    return {"awards": await refresh_catalog(session)}


@app.get("/api/v1/trends")
def trends_v1(request: Request, session: Session = Depends(get_session),
              key: str = Depends(require_product)):
    from app.omni.hubs import latest_web_payloads, trend_rows
    org = resolve_org(request)
    return trend_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/news")
def news_v1(request: Request, session: Session = Depends(get_session),
            key: str = Depends(require_product)):
    from app.omni.hubs import latest_web_payloads, news_rows
    org = resolve_org(request)
    return news_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/feeds")
def feeds_v1(request: Request, session: Session = Depends(get_session),
             key: str = Depends(require_product)):
    from app.omni.hubs import feed_rows, latest_web_payloads
    org = resolve_org(request)
    return feed_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/site")
def site_v1(request: Request, session: Session = Depends(get_session),
            key: str = Depends(require_product)):
    from app.omni.hubs import latest_web_payloads, site_rows
    org = resolve_org(request)
    return site_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/structured")
def structured_v1(request: Request, session: Session = Depends(get_session),
                  key: str = Depends(require_product)):
    from app.omni.hubs import latest_web_payloads, structured_rows
    org = resolve_org(request)
    return structured_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/surfaces")
def surfaces_v1(request: Request, session: Session = Depends(get_session),
                key: str = Depends(require_product)):
    from app.omni.hubs import latest_web_payloads, surface_rows
    org = resolve_org(request)
    return surface_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/legal")
def legal_v1(request: Request, session: Session = Depends(get_session),
             key: str = Depends(require_product)):
    from app.omni.hubs import latest_web_payloads, legal_rows
    org = resolve_org(request)
    return legal_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/identity")
def identity_v1(request: Request, session: Session = Depends(get_session),
                key: str = Depends(require_product)):
    from app.omni.hubs import identity_rows, latest_web_payloads
    org = resolve_org(request)
    return identity_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/onpage")
def onpage_v1(request: Request, session: Session = Depends(get_session),
              key: str = Depends(require_product)):
    from app.omni.hubs import latest_web_payloads, onpage_rows
    org = resolve_org(request)
    return onpage_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/locale")
def locale_v1(request: Request, session: Session = Depends(get_session),
              key: str = Depends(require_product)):
    from app.omni.hubs import latest_web_payloads, locale_rows
    org = resolve_org(request)
    return locale_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/desk")
def desk_v1(request: Request, session: Session = Depends(get_session),
            key: str = Depends(require_product)):
    org = resolve_org(request)
    return desk_rows(session, org.id if org else None)


@app.get("/api/v1/well-known")
def wellknown_v1(request: Request, session: Session = Depends(get_session),
                 key: str = Depends(require_product)):
    org = resolve_org(request)
    return wellknown_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/filings")
def filings_v1(request: Request, session: Session = Depends(get_session),
               key: str = Depends(require_product)):
    org = resolve_org(request)
    return filings_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/opportunities")
def opportunities_v1(request: Request, session: Session = Depends(get_session),
                     key: str = Depends(require_product)):
    from app.omni.hubs import latest_web_payloads, opportunity_rows
    org = resolve_org(request)
    return opportunity_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/socials")
def socials_v1(request: Request, session: Session = Depends(get_session),
               key: str = Depends(require_product)):
    from app.omni.hubs import latest_web_payloads, social_rows
    org = resolve_org(request)
    return social_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/coverage")
def coverage_v1(request: Request, session: Session = Depends(get_session),
                key: str = Depends(require_product)):
    from app.omni.hubs import coverage_rows, latest_web_payloads
    org = resolve_org(request)
    return [c.model_dump() for c in coverage_rows(
        latest_web_payloads(session, org.id if org else None))]


@app.get("/api/v1/contacts")
def contacts_v1(request: Request, session: Session = Depends(get_session),
                key: str = Depends(require_product)):
    from app.omni.hubs import contact_rows, latest_web_payloads
    org = resolve_org(request)
    return contact_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/unmeasured")
def unmeasured_v1(request: Request, session: Session = Depends(get_session),
                  key: str = Depends(require_product)):
    from app.omni.hubs import latest_web_payloads, unavailable_rows
    org = resolve_org(request)
    return unavailable_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/graph")
def graph_v1(request: Request, session: Session = Depends(get_session),
             key: str = Depends(require_product)):
    from app.omni.graphmap import build
    org = resolve_org(request)
    return build(session, org.id if org else None).model_dump()


@app.get("/api/v1/mentions")
def mentions_v1(request: Request, session: Session = Depends(get_session),
                key: str = Depends(require_product)):
    from app.omni.mentions import mention_rows
    org = resolve_org(request)
    return [m.model_dump() for m in mention_rows(session, org.id if org else None)]


@app.get("/api/v1/digest")
def digest_v1(request: Request, days: int = 7,
              session: Session = Depends(get_session),
              key: str = Depends(require_product)):
    from app.omni.digest import build
    org = resolve_org(request)
    return build(session, org.id if org else None, days=days).model_dump()


@app.get("/api/v1/tech")
def tech_v1(request: Request, session: Session = Depends(get_session),
            key: str = Depends(require_product)):
    from app.omni.hubs import latest_web_payloads, tech_rows
    org = resolve_org(request)
    return tech_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/competitors")
def competitors_v1(request: Request, session: Session = Depends(get_session),
                   key: str = Depends(require_product)):
    from app.omni.hubs import competitor_rows, latest_web_payloads
    org = resolve_org(request)
    return competitor_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/market")
def market_v1(request: Request, session: Session = Depends(get_session),
              key: str = Depends(require_product)):
    from app.omni.hubs import latest_web_payloads, market_rows
    org = resolve_org(request)
    return market_rows(latest_web_payloads(session, org.id if org else None))


@app.get("/api/v1/compare")
def compare_v1(a: str, b: str, request: Request,
               session: Session = Depends(get_session),
               key: str = Depends(require_product)):
    from app.omni.compare import compare_payloads, load_web_subject
    org = resolve_org(request)
    org_id = org.id if org else None
    left_rep, left = load_web_subject(session, a, org_id)
    right_rep, right = load_web_subject(session, b, org_id)
    intel = compare_payloads(
        left, right,
        left_href=f"/r/{left_rep.share_slug}" if left_rep else "",
        right_href=f"/r/{right_rep.share_slug}" if right_rep else "",
    )
    return intel.model_dump()


@app.get("/api/v1/events")
def events_v1(key: str = Depends(require_product)):
    from app.omni.events import recent
    return [{"name": e.name, "at": e.at, "payload": e.payload} for e in recent()]


@app.get("/api/v1/providers")
def providers_v1(key: str = Depends(require_product)):
    from app.omni.registry import registry
    return [{
        "name": p.name, "category": p.category, "status": p.status,
        "auth": p.auth, "capabilities": p.capabilities, "cost": p.cost,
        "fallbacks": p.fallbacks, "notes": p.notes,
        "health": {"calls": p.health.calls, "error_rate": round(p.health.error_rate, 3),
                   "avg_ms": round(p.health.avg_ms, 1)},
    } for p in registry()]


@app.get("/healthz")
def healthz():
    """Liveness only. Which sources are configured is operator information — it is
    on Settings and Diagnostics, not on an unauthenticated endpoint."""
    return JSONResponse({"ok": True, "app": settings.app_name})


# --------------------------------------------------------- discover / library / shortlists
@app.get("/discover", response_class=HTMLResponse)
async def discover_page(request: Request, q: str = "", platform: str = "any"):
    require_product(request)
    result = None
    if q.strip():
        from app.engine.discovery.creator_search import discover_creators
        result = (await discover_creators(q.strip(), platform=platform or "any")).to_dict()
    return _template(request, "discover.html", q=q, platform=platform or "any", result=result)


@app.get("/api/discover")
async def api_discover(request: Request, q: str, platform: str = "any",
                       limit: int = 20, key: str = Depends(require_product)):
    from app.engine.discovery.creator_search import discover_creators
    result = await discover_creators(q, platform=platform, limit=min(max(limit, 1), 40))
    return result.to_dict()


@app.get("/awards", response_class=HTMLResponse)
def awards_page(request: Request, session: Session = Depends(get_session)):
    require_product(request)
    from app.omni.award_dates import intel_from_row, stored_map
    from app.omni.awards import CATALOG
    freshness = stored_map(session)
    rows = []
    for award in CATALOG:
        row = freshness.get(award.name)
        intel = intel_from_row(row) if row else None
        dates = []
        if intel and intel.dates:
            dates = [f"{d.kind}: {d.raw}" for d in intel.dates[:4]]
        rows.append({
            "award": award,
            "status": row.status if row else "",
            "fetched_at": row.fetched_at if row else None,
            "reason": intel.reason if intel else "",
            "dates": dates,
        })
    return _template(request, "awards.html", catalog=rows)


@app.post("/awards/refresh")
async def awards_refresh_page(request: Request, session: Session = Depends(get_session)):
    require_product(request)
    from app.omni.award_dates import refresh_catalog
    await refresh_catalog(session)
    return RedirectResponse("/awards", status_code=303)


def _hub_page(request: Request, session: Session, *, title: str, eyebrow: str,
              intro: str, empty: str, note: str, headers: list[str],
              rows: list[dict]):
    require_product(request)
    return _template(request, "intel_hub.html", title=title, eyebrow=eyebrow,
                     intro=intro, empty=empty, note=note, headers=headers, rows=rows)


@app.get("/overview", response_class=HTMLResponse)
def overview_page(request: Request, session: Session = Depends(get_session)):
    require_product(request)
    from app.omni.hubs import overview_stats
    org = resolve_org(request)
    return _template(request, "overview.html",
                     stats=overview_stats(session, org.id if org else None))


@app.get("/market", response_class=HTMLResponse)
def market_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, market_rows
    org = resolve_org(request)
    rows = [{"href": r["href"], "cells": [r["subject"], r["name"], r["domain"], r["query"]]}
            for r in market_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Market intelligence", eyebrow="Market",
        intro="Official-site participants collected during Deep Analyze. Not TAM or share.",
        empty="No market maps yet. Deep Analyze a company or keyword.",
        note="Directories are dropped. A missing industry is INSUFFICIENT EVIDENCE, not zero.",
        headers=["Subject", "Participant", "Domain", "Query"], rows=rows)


@app.get("/competitors", response_class=HTMLResponse)
def competitors_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import competitor_rows, latest_web_payloads
    org = resolve_org(request)
    rows = [{"href": r["href"], "cells": [r["subject"], r["name"], r["domain"], r["snippet"]]}
            for r in competitor_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Competitor intelligence", eyebrow="Competitors",
        intro="Rivals that ranked for alternatives/competitors queries on analyzed subjects.",
        empty="No competitor lists yet. Deep Analyze a website with search configured.",
        note="G2, Capterra and social platforms are excluded.",
        headers=["Subject", "Rival", "Domain", "Why"], rows=rows)


@app.get("/compare", response_class=HTMLResponse)
def compare_page(request: Request, a: str = "", b: str = "",
                 session: Session = Depends(get_session)):
    require_product(request)
    from app.omni.compare import compare_payloads, load_web_subject, picker_subjects
    org = resolve_org(request)
    org_id = org.id if org else None
    intel = None
    error = ""
    if a.strip() and b.strip():
        left_rep, left = load_web_subject(session, a.strip(), org_id)
        right_rep, right = load_web_subject(session, b.strip(), org_id)
        if not left or not right:
            error = "One or both subjects have no stored website report."
        else:
            intel = compare_payloads(
                left, right,
                left_href=f"/r/{left_rep.share_slug}" if left_rep else "",
                right_href=f"/r/{right_rep.share_slug}" if right_rep else "",
            )
    return _template(
        request, "compare.html",
        subjects=picker_subjects(session, org_id),
        intel=intel, error=error, a_id=a.strip(), b_id=b.strip())


@app.get("/products", response_class=HTMLResponse)
def products_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, product_rows
    org = resolve_org(request)
    rows = []
    for r in product_rows(latest_web_payloads(session, org.id if org else None)):
        price = f"₹{r['price']:,.0f}" if r["price"] is not None else "—"
        rating = r["rating"] if r["rating"] is not None else "—"
        rows.append({"href": r["href"], "cells": [r["subject"], r["name"], price, rating]})
    return _hub_page(
        request, session, title="Product intelligence", eyebrow="Products",
        intro="Offers the sites themselves published as JSON-LD.",
        empty="No structured offers yet. Deep Analyze a product or pricing page.",
        note="Non-INR prices are dropped, not converted. Visible ₹ lines are not SKUs — they live on Structured and the report.",
        headers=["Subject", "Offer", "Price", "Rating"], rows=rows)


@app.get("/desk", response_class=HTMLResponse)
def desk_page(request: Request, session: Session = Depends(get_session)):
    require_product(request)
    org = resolve_org(request)
    rows = desk_rows(session, org.id if org else None)
    return _template(
        request, "desk.html",
        web_guide=[{"id": i, "title": t, "plain": p} for i, t, p in WEB_NEED_GUIDE],
        creator_guide=[{"id": i, "title": t, "plain": p} for i, t, p in CREATOR_NEED_GUIDE],
        rows=rows)


@app.get("/opportunities", response_class=HTMLResponse)
def opportunities_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, opportunity_rows
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["title"], r["why"], r["evidence"]]}
            for r in opportunity_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Opportunities", eyebrow="Actions",
        intro="Rule-driven gaps already computed on website reports. Not a growth forecast.",
        empty="No opportunities stored. Deep Analyze a website.",
        note="Each row cites a measured input. Empty is not 'no problems' — it means no rule fired.",
        headers=["Subject", "Opportunity", "Why", "Evidence"], rows=rows)


@app.get("/socials", response_class=HTMLResponse)
def socials_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, social_rows
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["platform"], r["handle"] or "—",
                       r["followers"], r["status"]]}
            for r in social_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Social surfaces", eyebrow="Social",
        intro="Accounts the website itself linked. Follower counts only when the public collector returned them.",
        empty="No social links stored. Deep Analyze a website.",
        note="A missing platform is not proof the brand is absent there.",
        headers=["Subject", "Platform", "Handle", "Followers", "Status"], rows=rows)


@app.get("/coverage", response_class=HTMLResponse)
def coverage_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import coverage_rows, latest_web_payloads
    org = resolve_org(request)
    rows = []
    for cov in coverage_rows(latest_web_payloads(session, org.id if org else None)):
        slots = cov.slots
        rows.append({
            "href": cov.href,
            "cells": [
                cov.subject,
                cov.score if cov.score is not None else "—",
                cov.assessed_n,
                slots.get("products", "—"),
                slots.get("competitors", "—"),
                slots.get("news", "—"),
                slots.get("feeds", "—"),
                slots.get("reviews", "—"),
                slots.get("market", "—"),
                slots.get("awards", "—"),
                slots.get("seo", "—"),
                slots.get("risk", "—"),
                slots.get("socials", "—"),
            ],
        })
    return _hub_page(
        request, session, title="Collection coverage", eyebrow="Coverage",
        intro="What this workspace measured on each stored website. Not how complete the company is.",
        empty="No website investigations yet. Deep Analyze a domain.",
        note="assessed = evidence found. empty = engine ran, found nothing. unavailable/missing = did not run. Download CSV at /export/coverage.csv",
        headers=["Subject", "Score", "Assessed", "Products", "Competitors", "News",
                 "Feeds", "Reviews", "Market", "Awards", "SEO", "Risk", "Socials"],
        rows=rows)


@app.get("/contacts", response_class=HTMLResponse)
def contacts_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import contact_rows, latest_web_payloads
    org = resolve_org(request)
    rows = [{"href": r["href"], "cells": [r["subject"], r["kind"], r["value"]]}
            for r in contact_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Public contacts", eyebrow="Contacts",
        intro="Emails and phone numbers published on sampled pages. Not a prospect list.",
        empty="No public contacts stored. Deep Analyze a website.",
        note="mailto/tel and visible addresses only. Private CRM data is not inferred.",
        headers=["Subject", "Kind", "Value"], rows=rows)


@app.get("/unmeasured", response_class=HTMLResponse)
def unmeasured_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, unavailable_rows
    org = resolve_org(request)
    rows = [{"href": r["href"], "cells": [r["subject"], r["item"], r["why"]]}
            for r in unavailable_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Unmeasured", eyebrow="Honesty",
        intro="Items already declared unavailable on stored website reports. Not a market gap list.",
        empty="No unavailable items stored. Deep Analyze a website.",
        note="These rows were printed on the report. They are not invented here. CSV: /export/unmeasured.csv",
        headers=["Subject", "Item", "Why"], rows=rows)


@app.get("/export/{table}.csv")
def export_table_csv(table: str, request: Request,
                     session: Session = Depends(get_session)):
    require_product(request)
    from app.omni.export import rows_to_csv
    from app.omni.hubs import (contact_rows, coverage_rows, feed_rows,
                               filings_rows, identity_rows, latest_web_payloads,
                               legal_rows, locale_rows, news_rows, onpage_rows,
                               opportunity_rows, site_rows, social_rows,
                               structured_rows, surface_rows, tech_rows,
                               unavailable_rows, wellknown_rows)
    from app.omni.mentions import mention_rows
    org = resolve_org(request)
    org_id = org.id if org else None
    payloads = latest_web_payloads(session, org_id)
    if table == "coverage":
        headers = ["subject", "domain", "score", "assessed", "empty", "unavailable",
                   "products", "competitors", "news", "feeds", "reviews", "market",
                   "awards", "seo", "risk", "socials"]
        rows = [[
            c.subject, c.domain, c.score, c.assessed_n, c.empty_n, c.unavailable_n,
            c.slots.get("products", ""), c.slots.get("competitors", ""),
            c.slots.get("news", ""), c.slots.get("feeds", ""),
            c.slots.get("reviews", ""),
            c.slots.get("market", ""), c.slots.get("awards", ""),
            c.slots.get("seo", ""), c.slots.get("risk", ""),
            c.slots.get("socials", ""),
        ] for c in coverage_rows(payloads)]
    elif table == "contacts":
        headers = ["subject", "kind", "value"]
        rows = [[r["subject"], r["kind"], r["value"]] for r in contact_rows(payloads)]
    elif table == "opportunities":
        headers = ["subject", "title", "why", "evidence"]
        rows = [[r["subject"], r["title"], r["why"], r["evidence"]]
                for r in opportunity_rows(payloads)]
    elif table == "socials":
        headers = ["subject", "platform", "handle", "followers", "status"]
        rows = [[r["subject"], r["platform"], r["handle"], r["followers"], r["status"]]
                for r in social_rows(payloads)]
    elif table == "news":
        headers = ["subject", "narrative", "title", "source", "published", "status"]
        rows = [[r["subject"], r["narrative"], r["title"], r["source"],
                 r["published"], r["status"]] for r in news_rows(payloads)]
    elif table == "feeds":
        headers = ["subject", "title", "published", "url", "source"]
        rows = [[r["subject"], r["title"], r["published"], r["url"], r["source"]]
                for r in feed_rows(payloads)]
    elif table == "site":
        headers = ["subject", "kind", "item", "value"]
        rows = [[r["subject"], r["kind"], r["item"], r["value"]]
                for r in site_rows(payloads)]
    elif table == "structured":
        headers = ["subject", "kind", "title", "detail"]
        rows = [[r["subject"], r["kind"], r["title"], r["detail"]]
                for r in structured_rows(payloads)]
    elif table == "surfaces":
        headers = ["subject", "kind", "host", "url"]
        rows = [[r["subject"], r["kind"], r["host"], r["url"]]
                for r in surface_rows(payloads)]
    elif table == "legal":
        headers = ["subject", "kind", "updated", "title", "url"]
        rows = [[r["subject"], r["kind"], r["updated"], r["title"], r["url"]]
                for r in legal_rows(payloads)]
    elif table == "identity":
        headers = ["subject", "kind", "value", "source"]
        rows = [[r["subject"], r["kind"], r["value"], r["source"]]
                for r in identity_rows(payloads)]
    elif table == "well-known":
        headers = ["subject", "role", "path", "present", "note"]
        rows = [[r["subject"], r["role"], r["path"], r["present"], r["note"]]
                for r in wellknown_rows(payloads)]
    elif table == "filings":
        headers = ["subject", "kind", "identifier", "name", "status", "latest"]
        rows = [[r["subject"], r["kind"], r["identifier"], r["name"],
                 r["status"], r["latest"]]
                for r in filings_rows(payloads)]
    elif table == "onpage":
        headers = ["subject", "kind", "provider", "url"]
        rows = [[r["subject"], r["kind"], r["provider"], r["url"]]
                for r in onpage_rows(payloads)]
    elif table == "locale":
        headers = ["subject", "kind", "value"]
        rows = [[r["subject"], r["kind"], r["value"]]
                for r in locale_rows(payloads)]
    elif table == "tech":
        headers = ["subject", "name", "category", "evidence"]
        rows = [[r["subject"], r["name"], r["category"], r["evidence"]]
                for r in tech_rows(payloads)]
    elif table == "unmeasured":
        headers = ["subject", "item", "why"]
        rows = [[r["subject"], r["item"], r["why"]] for r in unavailable_rows(payloads)]
    elif table == "mentions":
        headers = ["subject", "via", "mentioned", "domain", "evidence"]
        rows = [[m.subject, m.via, m.mentioned, m.mentioned_domain, m.evidence]
                for m in mention_rows(session, org_id)]
    elif table == "entities":
        query = select(Entity).order_by(Entity.updated_at.desc())
        if org is not None:
            query = query.where(Entity.org_id == org.id)
        else:
            query = query.where(Entity.org_id == None)  # noqa: E711
        headers = ["id", "name", "kind", "domain", "score", "watched", "updated_at"]
        rows = [[e.id, e.name, e.kind, e.domain, e.last_score,
                 "yes" if e.watched else "no", e.updated_at.isoformat()]
                for e in session.exec(query).all()[:200]]
    elif table == "alerts":
        query = select(Alert).order_by(Alert.created_at.desc())
        if org is not None:
            query = query.where(Alert.org_id == org.id)
        else:
            query = query.where(Alert.org_id == None)  # noqa: E711
        headers = ["created_at", "entity_id", "kind", "severity", "title", "detail"]
        rows = [[a.created_at.isoformat(), a.entity_id, a.kind, a.severity,
                 a.title, a.detail]
                for a in session.exec(query).all()[:200]]
    else:
        raise HTTPException(404, "unknown export table")
    body = rows_to_csv(headers, rows)
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{table}.csv"'},
    )


@app.get("/tech", response_class=HTMLResponse)
def tech_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, tech_rows
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["name"], r["category"], r["evidence"]]}
            for r in tech_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Technology map", eyebrow="Tech",
        intro="Fingerprints observed on sampled public pages. Server-side stacks stay invisible.",
        empty="No technology fingerprints stored. Deep Analyze a website.",
        note="A missing name is not proof the stack is absent — only that the public HTML did not match a known fingerprint.",
        headers=["Subject", "Technology", "Category", "Evidence"], rows=rows)


@app.get("/seo", response_class=HTMLResponse)
def seo_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, seo_rows
    org = resolve_org(request)
    rows = [{"href": r["href"], "cells": [r["subject"], r["domain"], r["missing"], r["thin"]]}
            for r in seo_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="SEO coverage", eyebrow="SEO",
        intro="Present / thin / missing commercial paths. Not a keyword-demand map.",
        empty="No coverage maps yet. Deep Analyze a website.",
        note="Demand × competition quadrants need a rank provider we do not invent. Printed noindex tokens live on Site signals.",
        headers=["Subject", "Domain", "Missing", "Thin"], rows=rows)


@app.get("/trends", response_class=HTMLResponse)
def trends_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, trend_rows
    org = resolve_org(request)
    rows = []
    for r in trend_rows(latest_web_payloads(session, org.id if org else None)):
        vel = f"{r['velocity']:+.1f}" if r["velocity"] is not None else "—"
        rows.append({"href": r["href"],
                     "cells": [r["subject"], r["class"], vel, r["score"]]})
    return _hub_page(
        request, session, title="Trend radar", eyebrow="SIGNAL",
        intro="Score-series classes for entities you have re-analyzed. Not search trends.",
        empty="No snapshot series yet. Deep Analyze the same domain twice.",
        note="EMERGING / ACCELERATING / PEAK / STABLE / DECLINING — or insufficient.",
        headers=["Subject", "Class", "Velocity", "Score"], rows=rows)


@app.get("/timeline", response_class=HTMLResponse)
def timeline_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.timeline import tenant_timeline
    org = resolve_org(request)
    rows = [{
        "href": e.href,
        "cells": [
            e.at.replace("T", " ")[:16],
            e.entity_name or e.entity_id or "—",
            e.kind,
            e.title,
            e.severity or "—",
        ],
    } for e in tenant_timeline(session, org.id if org else None)]
    return _hub_page(
        request, session, title="Timeline", eyebrow="Temporal",
        intro="Stored snapshots and watch alerts only. Nothing is backfilled or forecast here.",
        empty="No snapshots or alerts yet. Deep Analyze a website or run a watch sweep.",
        note="News items appear on the entity page from the last report payload, not this tenant feed.",
        headers=["When", "Entity", "Kind", "Event", "Severity"], rows=rows)


@app.get("/brand", response_class=HTMLResponse)
def brand_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import brand_rows, latest_web_payloads
    org = resolve_org(request)
    rows = []
    for r in brand_rows(latest_web_payloads(session, org.id if org else None)):
        rows.append({"href": r["href"],
                     "cells": [r["subject"], r["score"], r["socials"], r["tagline"]]})
    return _hub_page(
        request, session, title="Brand intelligence", eyebrow="Brand",
        intro="Public brand surface from website investigations: name, score, linked socials.",
        empty="No brand surfaces yet. Deep Analyze a website.",
        note="Awareness and recall are not measured. This is what the site publishes.",
        headers=["Entity", "Score", "Socials", "Self-description"], rows=rows)


@app.get("/content", response_class=HTMLResponse)
def content_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import content_rows
    org = resolve_org(request)
    rows = [{"href": r["href"], "cells": [r["subject"], r["items"], r["format"], r["hooks"]]}
            for r in content_rows(session, org.id if org else None)]
    return _hub_page(
        request, session, title="Content intelligence", eyebrow="Content DNA",
        intro="Measured title patterns from creator reports. Not a guessed hook library.",
        empty="No creator content analyses yet. Deep Analyze a profile with public posts.",
        note="Lift is vs that account's own median, not vs the open platform.",
        headers=["Creator", "Measured items", "Format", "Winning phrases"], rows=rows)


@app.get("/risk", response_class=HTMLResponse)
def risk_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, risk_rows
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["level"], r["crisis"], r["criticism"]]}
            for r in risk_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Risk radar", eyebrow="Risk",
        intro="Crisis and criticism labels from the news radar. Not a legal or credit score.",
        empty="No crisis/criticism narratives stored. Deep Analyze with search configured.",
        note="ELEVATED = two or more crisis snippets. Confirmation requires the source article.",
        headers=["Subject", "Level", "Crisis", "Criticism"], rows=rows)


@app.get("/news", response_class=HTMLResponse)
def news_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, news_rows
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["narrative"], r["title"],
                       r["source"] or "—", r["published"] or "—", r["status"]]}
            for r in news_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Narrative radar", eyebrow="News",
        intro="Search hits plus any article pages we fetched. Labels are keywords, not reach.",
        empty="No news items stored. Deep Analyze a company with search configured.",
        note="page_status fetched means we read the article. Circulation and sentiment scores stay unavailable.",
        headers=["Subject", "Narrative", "Headline", "Source", "Published", "Page"], rows=rows)


@app.get("/feeds", response_class=HTMLResponse)
def feeds_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import feed_rows, latest_web_payloads
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["title"], r["published"] or "—", r["url"] or "—"]}
            for r in feed_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="First-party feeds", eyebrow="Feeds",
        intro="RSS/Atom items the sites themselves advertised. Not search news and not traffic.",
        empty="No feed items stored. Deep Analyze a website that publishes a feed.",
        note="Dates are pubDate/published/updated fields. A title like '2024 recap' is not a date. CSV: /export/feeds.csv",
        headers=["Subject", "Title", "Published", "URL"], rows=rows)


@app.get("/site", response_class=HTMLResponse)
def site_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, site_rows
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["kind"], r["item"], r["value"]]}
            for r in site_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Site signals", eyebrow="Site",
        intro="robots.txt, conventional public files (including ads.txt), security/freshness headers, CSP host tokens, document link relations, off-host script hosts, and JSON-LD printed on sampled pages.",
        empty="No site signals stored. Deep Analyze a website.",
        note="Disallow is a published directive, not hidden inventory. Missing headers are not a CVE score. noindex is a printed token, not a ranking forecast. A CSP host is a policy token, not a live load. A listed manifest is not a PWA install. CSV: /export/site.csv",
        headers=["Subject", "Kind", "Item", "Value"], rows=rows)


@app.get("/structured", response_class=HTMLResponse)
def structured_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, structured_rows
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["kind"], r["title"], r["detail"] or "—"]}
            for r in structured_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Structured entities", eyebrow="Schema",
        intro="FAQ, jobs, events, articles, courses, ContactPoint, ItemList, AggregateOffer, OfferCatalog, speakable, WebPage lastReviewed, opening hours, HowTo tools, people, video, apps, NAP, share cards, visible ₹ lines, return/shipping prints and linked surfaces copied from sampled pages.",
        empty="No structured entities stored. Deep Analyze a website that publishes them.",
        note="A missing JobPosting is empty schema, not zero open roles. A ContactPoint is not a verified helpdesk. ItemList length is not inventory. An AggregateOffer range is not a market price. OfferCatalog names are not a complete catalog. dateModified and lastReviewed are not verified edits. Speakable selectors are not a featured-snippet rank. significantLink URLs are listed, not fetched. Opening hours are printed slots, not an open-now verdict. HowTo tools are printed names, not a shopping list. totalTime is not a completion forecast. Course count is not enrollment. twitter:site is not followers. Visible ₹ lines are not SKUs. CSV: /export/structured.csv",
        headers=["Subject", "Kind", "Title", "Detail"], rows=rows)


@app.get("/surfaces", response_class=HTMLResponse)
def surfaces_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, surface_rows
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["kind"], r["host"] or "—", r["url"]]}
            for r in surface_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Declared surfaces", eyebrow="Surfaces",
        intro="App store, GitHub and status URLs the site itself linked. Not a name-search.",
        empty="No app store, GitHub or status URL was linked from stored pages.",
        note="Absence is empty, not 'they have no repo'. We do not invent /status. CSV: /export/surfaces.csv",
        headers=["Subject", "Kind", "Host", "URL"], rows=rows)


@app.get("/legal", response_class=HTMLResponse)
def legal_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, legal_rows
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["kind"], r["updated"] or "—",
                       r["title"] or "—", r["url"]]}
            for r in legal_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Legal pages", eyebrow="Legal",
        intro="Privacy, terms, cookie and refund pages that were in the crawl sample. Dates sit next to last-updated wording.",
        empty="No policy page was sampled. A homepage link we did not fetch is not a missing policy.",
        note="A footer year is not a revision date. This is not a compliance score. CSV: /export/legal.csv",
        headers=["Subject", "Kind", "Updated", "Title", "URL"], rows=rows)


@app.get("/identity", response_class=HTMLResponse)
def identity_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import identity_rows, latest_web_payloads
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["kind"], r["value"], r["source"]]}
            for r in identity_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Printed identifiers", eyebrow="Identity",
        intro="GSTIN (checksum), CIN (pattern), Organization tax/VAT/LEI/logo, verification meta kinds, rel=me and JSON-LD sameAs URLs.",
        empty="No GSTIN, CIN, schema tax/VAT/LEI/logo, verification meta, rel=me or sameAs stored.",
        note="A matching string is not a GST or MCA verification. A google-site-verification tag is not Search Console status. rel=me and sameAs are listed, not fetched, and never merge keys. A sameAs host is not a follower count. CSV: /export/identity.csv",
        headers=["Subject", "Kind", "Value", "Source"], rows=rows)


@app.get("/well-known", response_class=HTMLResponse)
def wellknown_page(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["role"], r["path"], r["present"],
                       r["note"] or "—"]}
            for r in wellknown_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Well-known inventory", eyebrow="Trust / AI",
        intro="security.txt, llms.txt, humans.txt and the other conventional files we already fetch. This is an inventory of published trust and AI surfaces — not a security score and not traffic.",
        empty="No conventional public files stored. Deep Analyze a website.",
        note="llms.txt is a crawl invitation, not sessions. A Contact: line is not SOC 2. humans.txt credits are not a headcount. ads.txt is not spend. Other well-known paths are not invented. CSV: /export/well-known.csv",
        headers=["Subject", "Role", "Path", "Present", "Note"], rows=rows)


@app.get("/filings", response_class=HTMLResponse)
def filings_page(request: Request, session: Session = Depends(get_session)):
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["kind"], r["identifier"], r["name"] or "—",
                       r["status"] or "—", r["latest"] or "—"]}
            for r in filings_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Official filings", eyebrow="Filings",
        intro="SEC EDGAR and GLEIF run only when a CIK or LEI already existed on the page or Wikidata. CIN is recorded; MCA text stays unavailable. Valuation is never stored.",
        empty="No CIK, LEI or CIN was already present on a stored report.",
        note="A ticker or SIC code is not a share price. GLEIF status is not creditworthiness. A matching CIN is not an MCA lookup. CSV: /export/filings.csv",
        headers=["Subject", "Registry", "Identifier", "Name", "Status", "Latest"], rows=rows)


@app.get("/onpage", response_class=HTMLResponse)
def onpage_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, onpage_rows
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["kind"], r["provider"], r["url"]]}
            for r in onpage_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="On-page surfaces", eyebrow="On-page",
        intro="Iframes, form actions, click-to-chat links and .pdf hrefs copied from sampled pages.",
        empty="No embed, form, chat link or PDF href stored.",
        note="Linked PDFs are listed, not fetched or OCR'd. We do not invent /brochure.pdf. CSV: /export/onpage.csv",
        headers=["Subject", "Kind", "Provider", "URL"], rows=rows)


@app.get("/locale", response_class=HTMLResponse)
def locale_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, locale_rows
    org = resolve_org(request)
    rows = [{"href": r["href"],
             "cells": [r["subject"], r["kind"], r["value"]]}
            for r in locale_rows(latest_web_payloads(session, org.id if org else None))]
    return _hub_page(
        request, session, title="Locale tags", eyebrow="Locale",
        intro="html lang, og:locale, Content-Language and same-host hreflang copied from sampled pages.",
        empty="No locale tag stored. A language in the body copy is not a tag.",
        note="A language tag is not a market, a TAM, or proof they operate in a country. CSV: /export/locale.csv",
        headers=["Subject", "Kind", "Value"], rows=rows)


@app.get("/mentions", response_class=HTMLResponse)
def mentions_page(request: Request, session: Session = Depends(get_session)):
    require_product(request)
    from app.omni.mentions import mention_rows
    org = resolve_org(request)
    rows = [{"href": r.href,
             "cells": [r.subject, r.via, r.mentioned, r.mentioned_domain, r.evidence]}
            for r in mention_rows(session, org.id if org else None)]
    return _hub_page(
        request, session, title="Cross-entity mentions", eyebrow="Mentions",
        intro="A stored domain appearing in another subject's competitors, market map, or news. Names never count.",
        empty="No domain overlap between stored investigations yet.",
        note="This is identifier overlap in stored payloads, not a claim the companies are related.",
        headers=["Subject", "Via", "Mentioned", "Domain", "Evidence"], rows=rows)


@app.get("/graph", response_class=HTMLResponse)
def graph_page(request: Request, session: Session = Depends(get_session)):
    require_product(request)
    from app.omni.graphmap import build
    org = resolve_org(request)
    return _template(request, "graph.html", g=build(session, org.id if org else None))


@app.get("/api/v1")
def api_v1_index():
    """Machine-readable map of the versioned API."""
    return {
        "version": "v1",
        "openapi": "/openapi.json",
        "docs": "/docs",
        "endpoints": [
            "POST /api/v1/analyze", "GET /api/v1/analysis/{id}",
            "GET /api/v1/entities", "GET /api/v1/entities/{id}",
            "GET /api/v1/entities/{id}/timeline",
            "POST /api/v1/entities/resolve",
            "POST /api/v1/watchlists", "POST /api/v1/watchlists/run",
            "GET /api/v1/alerts", "GET /api/v1/digest", "GET /api/v1/timeline",
            "GET /api/v1/awards", "POST /api/v1/awards/refresh", "GET /api/v1/events",
            "GET /api/v1/providers", "GET /api/v1/trends", "GET /api/v1/news",
            "GET /api/v1/feeds", "GET /api/v1/site", "GET /api/v1/structured",
            "GET /api/v1/surfaces", "GET /api/v1/legal", "GET /api/v1/identity",
            "GET /api/v1/onpage", "GET /api/v1/locale",
            "GET /api/v1/well-known", "GET /api/v1/filings",
            "GET /api/v1/tech", "GET /api/v1/desk", "GET /api/v1/opportunities",
            "GET /api/v1/socials",
            "GET /api/v1/coverage", "GET /api/v1/contacts",
            "GET /api/v1/unmeasured",
            "GET /api/v1/graph", "GET /api/v1/mentions",
            "GET /api/v1/competitors", "GET /api/v1/compare", "GET /api/v1/market",
        ],
    }


@app.get("/reviews", response_class=HTMLResponse)
def reviews_page(request: Request, session: Session = Depends(get_session)):
    from app.omni.hubs import latest_web_payloads, review_rows
    org = resolve_org(request)
    rows = []
    for r in review_rows(latest_web_payloads(session, org.id if org else None)):
        rows.append({"href": r["href"],
                     "cells": [r["subject"], r["rating"] or "—", r["count"] or "—", r["themes"]]})
    return _hub_page(
        request, session, title="Review intelligence", eyebrow="Reviews",
        intro="On-page JSON-LD Review bodies and printed AggregateRating (Organization, LocalBusiness, Product). Third-party platforms are not scraped.",
        empty="No on-page Review or AggregateRating schema stored. Empty is not 'they have no reviews'.",
        note="ratingValue and reviewCount are printed fields, not a verified review volume. Themes are keyword buckets on the review body, not a trained classifier. Body copy such as '4.9 stars' is ignored.",
        headers=["Subject", "Rating", "Count", "Themes"], rows=rows)


def _render_research(request: Request, session: Session, *, q: str = "",
                     result: dict | None = None, error: str = ""):
    require_product(request)
    org = resolve_org(request)
    docs = list(session.exec(
        select(SourceDocument).order_by(SourceDocument.created_at.desc())).all())
    if org is not None:
        docs = [d for d in docs if d.org_id == org.id]
    else:
        docs = [d for d in docs if d.org_id is None]
    return _template(request, "research.html", q=q, result=result, error=error,
                     documents=docs[:50], max_mb=settings.max_document_mb)


@app.get("/research", response_class=HTMLResponse)
def research_page(request: Request, session: Session = Depends(get_session)):
    return _render_research(request, session)


@app.post("/research", response_class=HTMLResponse)
def research_resolve(request: Request, q: str = Form(...),
                     session: Session = Depends(get_session)):
    require_product(request)
    from app.omni.graph import lookup
    from app.omni.input_resolver import classify
    try:
        ui = classify(q)
    except ValueError as exc:
        return _render_research(request, session, q=q, error=str(exc))
    org = resolve_org(request)
    result = lookup(session, org_id=org.id if org else None, kind=ui.kind,
                    value=ui.value, platform=ui.platform, handle=ui.handle,
                    domain=ui.domain)
    return _render_research(request, session, q=q, result=result)


@app.post("/research/documents", response_class=HTMLResponse)
async def research_document(request: Request, session: Session = Depends(get_session),
                            file: UploadFile = File(...)):
    require_product(request)
    from app.omni.documents import (ALLOWED_SUFFIX, analyse_text, extract_text,
                                    sniff_suffix)
    name = Path(file.filename or "upload").name
    suffix = sniff_suffix(name)
    if suffix not in ALLOWED_SUFFIX:
        return _render_research(request, session, error="Allowed: PDF, DOCX, TXT, CSV, HTML.")
    blob = await file.read()
    if len(blob) > settings.max_document_mb * 1024 * 1024:
        return _render_research(request, session, error="File exceeds the size limit.")
    dest_dir = Path(settings.documents_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored = dest_dir / f"{uuid.uuid4().hex}{suffix}"
    stored.write_bytes(blob)
    try:
        text = extract_text(stored, suffix)
        intel = analyse_text(text, filename=name, media_type=file.content_type or suffix)
    except Exception as exc:  # noqa: BLE001
        stored.unlink(missing_ok=True)
        return _render_research(request, session, error=f"Could not extract text: {exc}")
    org = resolve_org(request)
    row = SourceDocument(
        id=uuid.uuid4().hex[:12],
        org_id=org.id if org else None,
        filename=name[:200],
        media_type=(file.content_type or suffix)[:80],
        stored_path=str(stored),
        chars=intel.chars,
        excerpt=intel.excerpt[:400],
        intel_json=intel.model_dump_json(),
    )
    session.add(row)
    session.commit()
    return RedirectResponse("/research", status_code=303)


@app.get("/entities", response_class=HTMLResponse)
def entities_page(request: Request, session: Session = Depends(get_session)):
    require_product(request)
    org = resolve_org(request)
    query = select(Entity).order_by(Entity.updated_at.desc())
    if org is not None:
        query = query.where(Entity.org_id == org.id)
    else:
        query = query.where(Entity.org_id == None)  # noqa: E711
    rows = list(session.exec(query).all())[:200]
    return _template(request, "entities.html", entities=rows)


@app.get("/entities/{entity_id}", response_class=HTMLResponse)
def entity_page(entity_id: str, request: Request,
                session: Session = Depends(get_session)):
    require_product(request)
    entity = session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(404, "entity not found")
    org = resolve_org(request)
    if org is not None and entity.org_id != org.id:
        raise HTTPException(404, "entity not found")
    if org is None and entity.org_id is not None:
        raise HTTPException(404, "entity not found")
    from app.omni.coverage import from_payload
    from app.omni.graph import aliases_for, links_for
    from app.omni.hubs import related_documents
    from app.omni.timeline import brief_from_report, from_stores
    report = session.get(Report, entity.last_report_id) if entity.last_report_id else None
    org_id = org.id if org else None
    evidence = list(session.exec(
        select(EvidenceItem).where(EvidenceItem.entity_id == entity.id)).all())[:20]
    linked_reports = []
    for _link, other in links_for(session, entity.id):
        if other.last_report_id:
            other_rep = session.get(Report, other.last_report_id)
            if other_rep:
                linked_reports.append((other, other_rep))
    coverage = None
    if report and report.kind == "web" and report.payload_json:
        try:
            payload = json.loads(report.payload_json)
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            coverage = from_payload(
                payload,
                subject=payload.get("entity_name") or entity.name,
                href=f"/r/{report.share_slug}",
            )
    return _template(
        request, "entity.html", entity=entity,
        aliases=aliases_for(session, entity.id),
        links=links_for(session, entity.id),
        report=report,
        evidence=evidence,
        documents=related_documents(session, entity, org_id),
        linked_reports=linked_reports,
        brief=brief_from_report(report),
        timeline=from_stores(session, entity.id, report=report),
        coverage=coverage,
    )


@app.get("/api/v1/entities")
def entities_v1(request: Request, session: Session = Depends(get_session),
                key: str = Depends(require_product)):
    org = resolve_org(request)
    query = select(Entity).order_by(Entity.updated_at.desc())
    if org is not None:
        query = query.where(Entity.org_id == org.id)
    else:
        query = query.where(Entity.org_id == None)  # noqa: E711
    return [{
        "id": e.id, "kind": e.kind, "name": e.name, "domain": e.domain,
        "score": e.last_score, "report_id": e.last_report_id,
        "watched": bool(e.watched),
        "updated_at": e.updated_at.isoformat(),
    } for e in session.exec(query).all()[:200]]


@app.post("/entities/{entity_id}/watch")
def entity_watch(entity_id: str, request: Request,
                 session: Session = Depends(get_session)):
    require_product(request)
    entity = session.get(Entity, entity_id)
    if not entity:
        raise HTTPException(404, "entity not found")
    org = resolve_org(request)
    if org is not None and entity.org_id != org.id:
        raise HTTPException(404, "entity not found")
    if org is None and entity.org_id is not None:
        raise HTTPException(404, "entity not found")
    entity.watched = not bool(entity.watched)
    session.add(entity)
    session.commit()
    return RedirectResponse("/entities", status_code=303)


@app.get("/digest", response_class=HTMLResponse)
def digest_page(request: Request, days: int = 7,
                session: Session = Depends(get_session)):
    require_product(request)
    from app.omni.digest import build
    org = resolve_org(request)
    return _template(
        request, "digest.html",
        intel=build(session, org.id if org else None, days=days))


@app.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, session: Session = Depends(get_session)):
    require_product(request)
    org = resolve_org(request)
    query = select(Alert).order_by(Alert.created_at.desc())
    if org is not None:
        query = query.where(Alert.org_id == org.id)
    else:
        query = query.where(Alert.org_id == None)  # noqa: E711
    rows = list(session.exec(query).all())[:200]
    names = {}
    for row in rows:
        if row.entity_id not in names:
            ent = session.get(Entity, row.entity_id)
            names[row.entity_id] = ent.name if ent else row.entity_id
    return _template(request, "alerts.html", alerts=rows, entity_names=names)


@app.post("/watch/run")
async def watch_run_page(request: Request, session: Session = Depends(get_session)):
    require_product(request)
    from app.omni.watch import run_sweep
    org = resolve_org(request)
    await run_sweep(session, org.id if org else None)
    return RedirectResponse("/alerts", status_code=303)


@app.get("/api/v1/alerts")
def alerts_v1(request: Request, session: Session = Depends(get_session),
              key: str = Depends(require_product)):
    org = resolve_org(request)
    query = select(Alert).order_by(Alert.created_at.desc())
    if org is not None:
        query = query.where(Alert.org_id == org.id)
    else:
        query = query.where(Alert.org_id == None)  # noqa: E711
    return [{
        "id": a.id, "entity_id": a.entity_id, "kind": a.kind,
        "severity": a.severity, "title": a.title, "detail": a.detail,
        "created_at": a.created_at.isoformat(), "read": a.read,
    } for a in session.exec(query).all()[:200]]


@app.get("/library", response_class=HTMLResponse)
def library_page(request: Request, q: str = "", verdict: str = "", sort: str = "newest",
                 session: Session = Depends(get_session)):
    require_product(request)
    org = resolve_org(request)
    query = select(Report)
    if org is not None:
        query = query.where(Report.org_id == org.id)
    else:
        query = query.where(Report.org_id == None)  # noqa: E711
    rows = _live_reports(list(session.exec(query).all()))
    ql = q.strip().lower()
    if ql:
        rows = [r for r in rows if ql in (r.subject_name or "").lower()
                or ql in (r.subject_handle or "").lower()]
    if verdict:
        rows = [r for r in rows if (r.media_verdict or "") == verdict]
    if sort == "fit":
        rows = sorted(rows, key=lambda r: (
            r.fit_score is not None, r.fit_score or 0, r.created_at), reverse=True)
    elif sort == "confidence":
        rows = sorted(rows, key=lambda r: (r.overall_confidence, r.created_at), reverse=True)
    else:
        rows = sorted(rows, key=lambda r: r.created_at, reverse=True)
    return _template(request, "library.html", reports=rows[:200], q=q, verdict=verdict, sort=sort)


def _default_shortlist(session: Session, org_id: str | None, created_by: str | None) -> Shortlist:
    rows = list(session.exec(select(Shortlist)).all())
    if org_id is not None:
        rows = [r for r in rows if r.org_id == org_id]
    else:
        rows = [r for r in rows if r.org_id is None]
    if rows:
        return sorted(rows, key=lambda r: r.updated_at, reverse=True)[0]
    sl = Shortlist(id=uuid.uuid4().hex[:12], org_id=org_id, name="Default shortlist",
                   brief="Auto-created. Rename anytime.", created_by=created_by)
    session.add(sl)
    session.commit()
    session.refresh(sl)
    return sl


@app.get("/shortlists", response_class=HTMLResponse)
def shortlists_page(request: Request, session: Session = Depends(get_session)):
    require_product(request)
    org = resolve_org(request)
    lists = list(session.exec(select(Shortlist).order_by(Shortlist.updated_at.desc())).all())
    if org is not None:
        lists = [r for r in lists if r.org_id == org.id]
    else:
        lists = [r for r in lists if r.org_id is None]
    enriched = []
    for sl in lists:
        n = len(session.exec(select(ShortlistItem).where(ShortlistItem.shortlist_id == sl.id)).all())
        row = sl.model_dump()
        row["item_count"] = n
        enriched.append(type("SL", (), row)())
    return _template(request, "shortlists.html", lists=enriched)


@app.post("/shortlists")
def shortlists_create(request: Request, name: str = Form(...), brief: str = Form(""),
                      session: Session = Depends(get_session)):
    require_product(request)
    org = resolve_org(request)
    sl = Shortlist(id=uuid.uuid4().hex[:12], org_id=org.id if org else None,
                   name=name.strip()[:120], brief=(brief or "").strip()[:2000])
    session.add(sl)
    session.commit()
    return RedirectResponse(f"/shortlists/{sl.id}", status_code=303)


@app.get("/shortlists/{shortlist_id}", response_class=HTMLResponse)
def shortlist_detail(shortlist_id: str, request: Request,
                     session: Session = Depends(get_session)):
    require_product(request)
    sl = session.get(Shortlist, shortlist_id)
    if not sl:
        raise HTTPException(404)
    org = resolve_org(request)
    if org is not None and sl.org_id != org.id:
        raise HTTPException(404)
    if org is None and sl.org_id is not None:
        raise HTTPException(404)
    items = list(session.exec(select(ShortlistItem)
                              .where(ShortlistItem.shortlist_id == sl.id)
                              .order_by(ShortlistItem.created_at.desc())).all())
    view = []
    for it in items:
        slug = None
        if it.report_id:
            rep = session.get(Report, it.report_id)
            slug = rep.share_slug if rep else None
        d = it.model_dump()
        d["report_slug"] = slug
        view.append(d)
    return _template(request, "shortlist_detail.html", sl=sl, items=view)


@app.post("/shortlists/quick-add")
async def shortlist_quick_add(request: Request, session: Session = Depends(get_session)):
    require_product(request)
    form = dict(await request.form())
    org = resolve_org(request)
    org_id = org.id if org else None
    sl = _default_shortlist(session, org_id, None)
    report_id = (form.get("report_id") or "").strip() or None
    platform = (form.get("platform") or "").strip()
    handle = (form.get("handle") or "").strip()
    url = (form.get("url") or "").strip()
    display_name = (form.get("display_name") or "").strip()
    fit = None
    verdict = None
    if report_id:
        rep = session.get(Report, report_id)
        if not rep:
            raise HTTPException(404, "report not found")
        _assert_report_access(request, rep)
        if rep.kind == "cohort":
            # A cohort row's subject_handle is a label like "3 creators", not a key —
            # copying it into a shortlist item would corrupt the handle join.
            raise HTTPException(
                422, "This is a cohort report covering several creators. Shortlist the "
                     "creators individually so each entry keeps a real handle.")
        if rep.kind in ("web", "media"):
            raise HTTPException(
                422, "Shortlists are creator rosters. This report is not a creator "
                     "profile; shortlist the entity's creator accounts individually.")
        handle = handle or rep.subject_handle.lstrip("@")
        display_name = display_name or rep.subject_name
        url = url or rep.seed_url
        fit = rep.fit_score
        verdict = rep.media_verdict
    item = ShortlistItem(
        id=uuid.uuid4().hex[:12], shortlist_id=sl.id, report_id=report_id,
        platform=platform, handle=handle.lstrip("@"), url=url,
        display_name=display_name or handle, fit_score=fit, media_verdict=verdict,
    )
    sl.updated_at = datetime.utcnow()
    session.add(item)
    session.add(sl)
    session.commit()
    return RedirectResponse(f"/shortlists/{sl.id}", status_code=303)


@app.post("/shortlists/{shortlist_id}/items/{item_id}/status")
def shortlist_item_status(shortlist_id: str, item_id: str, request: Request,
                          status_value: str = Form(..., alias="status"),
                          session: Session = Depends(get_session)):
    require_product(request)
    sl = session.get(Shortlist, shortlist_id)
    it = session.get(ShortlistItem, item_id)
    if not sl or not it or it.shortlist_id != sl.id:
        raise HTTPException(404)
    org = resolve_org(request)
    if org is not None and sl.org_id != org.id:
        raise HTTPException(404)
    if status_value in {"shortlisted", "outreach", "negotiating", "won", "pass"}:
        it.status = status_value
        sl.updated_at = datetime.utcnow()
        session.add(it); session.add(sl); session.commit()
    return RedirectResponse(f"/shortlists/{shortlist_id}", status_code=303)


@app.post("/shortlists/{shortlist_id}/items/{item_id}/delete")
def shortlist_item_delete(shortlist_id: str, item_id: str, request: Request,
                          session: Session = Depends(get_session)):
    require_product(request)
    sl = session.get(Shortlist, shortlist_id)
    it = session.get(ShortlistItem, item_id)
    if not sl or not it or it.shortlist_id != sl.id:
        raise HTTPException(404)
    org = resolve_org(request)
    if org is not None and sl.org_id != org.id:
        raise HTTPException(404)
    session.delete(it)
    sl.updated_at = datetime.utcnow()
    session.add(sl)
    session.commit()
    return RedirectResponse(f"/shortlists/{shortlist_id}", status_code=303)
