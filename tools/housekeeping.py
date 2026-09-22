"""Storage hygiene.

Reports are ephemeral: by default each pack is deleted after REPORT_TTL_MINUTES
(5). A background loop sweeps every 20 seconds so a report dies even if nobody
runs another analysis. Download HTML, JSON or Word before the timer ends.

The HTTP cache is still pruned against CACHE_TTL_HOURS / MAX_CACHE_MB.

Nothing here deletes a report that is still inside the TTL window, and the counts
are always reported back so the UI can show what happened.

Deletion has to be complete to be honest: a report row leaves together with the job
that collected it (the job row holds the raw collected data, including anything an
analyst pasted in), and stored paths resolve against the project root — never against
whatever directory the process happened to start in — so a purge cannot report
"cleared" while leaving files or rows behind.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from app.config import settings

ROOT = Path(__file__).resolve().parents[1]

# Jobs that will never move again, or are parked waiting on a human. Queued and
# running jobs are in flight and are never pruned.
_TERMINAL_JOB_STATES = {"done", "failed", "needs_input"}


@dataclass
class Swept:
    reports_deleted: int = 0
    jobs_deleted: int = 0
    files_deleted: int = 0
    cache_files_deleted: int = 0
    bytes_freed: int = 0
    reports_kept: int = 0
    cache_mb: float = 0.0
    reports_mb: float = 0.0
    db_mb: float = 0.0


def _resolve(path: str | Path) -> Path:
    """Anchor a stored path to the project root.

    .env may point REPORTS_DIR / CACHE_DIR / DATABASE_URL at relative values, so a
    stored path only means something relative to the install, not to the process CWD.
    """
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def _rm(path: str | Path | None, s: Swept, *, cache: bool = False) -> None:
    """Delete one file and count it honestly — a missing file is not "deleted"."""
    if not path:
        return
    p = _resolve(path)
    if not p.is_file():
        return
    size = p.stat().st_size
    try:
        p.unlink()
    except OSError:
        return
    s.bytes_freed += size
    if cache:
        s.cache_files_deleted += 1
    else:
        s.files_deleted += 1


def _rm_report_files(report, s: Swept) -> None:
    _rm(report.html_path, s)
    _rm(report.docx_path, s)


def _delete_job_if_unreferenced(db: Session, job_id: str | None, s: Swept) -> None:
    """Delete a job row once no report references it.

    The job holds the raw collected data and any analyst-pasted numbers — it is the
    report's data under another key, so it must leave with the report.
    """
    from app.models import Job, Report

    if not job_id:
        return
    if db.exec(select(Report).where(Report.job_id == job_id)).first():
        return
    job = db.get(Job, job_id)
    if job is not None:
        db.delete(job)
        s.jobs_deleted += 1


def _db_mb() -> float:
    """Size of the SQLite database itself. It holds every report's raw collected
    data, so a usage readout that skips it underreports what is actually stored."""
    prefix = "sqlite:///"
    url = settings.database_url
    if not url.startswith(prefix):
        return 0.0
    try:
        return round(_resolve(url[len(prefix):]).stat().st_size / 1_048_576, 1)
    except OSError:
        return 0.0


def disk_usage() -> dict[str, float]:
    def mb(folder: str) -> float:
        root = _resolve(folder)
        if not root.exists():
            return 0.0
        return round(sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
                     / 1_048_576, 1)
    return {"reports_mb": mb(settings.reports_dir),
            "cache_mb": mb(settings.cache_dir),
            "db_mb": _db_mb()}


def _fill_usage(s: Swept) -> None:
    usage = disk_usage()
    s.reports_mb = usage["reports_mb"]
    s.cache_mb = usage["cache_mb"]
    s.db_mb = usage["db_mb"]


def age_cutoff() -> datetime | None:
    """Reports older than this are deleted. Minutes win over days."""
    minutes = int(getattr(settings, "report_ttl_minutes", 0) or 0)
    if minutes > 0:
        return datetime.utcnow() - timedelta(minutes=minutes)
    days = int(settings.retention_days or 0)
    if days > 0:
        return datetime.utcnow() - timedelta(days=days)
    return None


def remaining_seconds(created_at: datetime | None) -> int | None:
    minutes = int(getattr(settings, "report_ttl_minutes", 0) or 0)
    if minutes <= 0 or created_at is None:
        return None
    left = (created_at + timedelta(minutes=minutes) - datetime.utcnow()).total_seconds()
    return max(0, int(left))


def is_expired(created_at: datetime | None) -> bool:
    left = remaining_seconds(created_at)
    return left is not None and left <= 0


def sweep(engine) -> Swept:
    """Prune reports, jobs and cache to the configured limits. Safe after every run."""
    from app.models import Job, Report

    s = Swept()

    with Session(engine) as db:
        rows = db.exec(select(Report).order_by(Report.created_at.desc())).all()
        doomed: list[Report] = []

        cutoff = age_cutoff()
        if cutoff is not None:
            doomed += [r for r in rows if r.created_at < cutoff]

        if settings.max_reports and len(rows) > settings.max_reports:
            doomed += [r for r in rows[settings.max_reports:] if r not in doomed]

        for r in doomed:
            _rm_report_files(r, s)
            db.delete(r)
            s.reports_deleted += 1
        # The job that collected a doomed report holds the same data; it goes too.
        for job_id in {r.job_id for r in doomed}:
            _delete_job_if_unreferenced(db, job_id, s)
        # Terminal jobs that outlived the retention window without a live report
        # (failed runs, abandoned paste-forms) are bound by the same policy.
        if cutoff is not None:
            stale = db.exec(select(Job).where(Job.created_at < cutoff)).all()
            for job in stale:
                if job.status in _TERMINAL_JOB_STATES:
                    _delete_job_if_unreferenced(db, job.id, s)
        if doomed or s.jobs_deleted:
            db.commit()
        s.reports_kept = len(rows) - len(doomed)

    # cache: drop expired entries first, then oldest-first until under the size cap
    cache = _resolve(settings.cache_dir)
    if cache.exists():
        files = [f for f in cache.iterdir() if f.is_file()]
        now = time.time()
        keep = []
        for f in files:
            age_h = (now - f.stat().st_mtime) / 3600
            if age_h > settings.cache_ttl_hours:
                _rm(f, s, cache=True)
            else:
                keep.append(f)
        if settings.max_cache_mb:
            cap = settings.max_cache_mb * 1_048_576
            total = sum(f.stat().st_size for f in keep)
            for f in sorted(keep, key=lambda x: x.stat().st_mtime):
                if total <= cap:
                    break
                total -= f.stat().st_size
                _rm(f, s, cache=True)

    _fill_usage(s)
    return s


def purge_all(engine) -> Swept:
    """Delete every stored report, every collection job and the whole cache.

    The settings UI promises a complete clear-out, so it must be one: report rows, the
    job rows holding the raw collected data, every file in the reports directory —
    including files no database row references any more — and every cache file.
    """
    from app.models import Alert, Entity, EntitySnapshot, EvidenceItem, Job, Report

    s = Swept()
    with Session(engine) as db:
        for r in db.exec(select(Report)).all():
            _rm_report_files(r, s)
            db.delete(r)
            s.reports_deleted += 1
        for job in db.exec(select(Job)).all():
            db.delete(job)
            s.jobs_deleted += 1
        for item in db.exec(select(EvidenceItem)).all():
            db.delete(item)
        for snap in db.exec(select(EntitySnapshot)).all():
            db.delete(snap)
        for alert in db.exec(select(Alert)).all():
            db.delete(alert)
        for ent in db.exec(select(Entity)).all():
            db.delete(ent)
        db.commit()

    reports = _resolve(settings.reports_dir)
    if reports.exists():
        for f in reports.iterdir():
            if f.is_file():
                _rm(f, s)
    cache = _resolve(settings.cache_dir)
    if cache.exists():
        for f in cache.iterdir():
            if f.is_file():
                _rm(f, s, cache=True)

    _fill_usage(s)
    return s


def wipe_identities(engine) -> Swept:
    """Delete every account, licence, report and stored identity.

    Plans stay. Used when the product drops customer accounts for the public
    email-only flow.
    """
    from app.commercial.models import (AuditLog, DeviceBinding, LicenseKey, Org,
                                       Subscription, UsageRecord, WebhookEvent)
    from app.models import (AwardFreshness, EntityAlias, EntityLink, Shortlist,
                            ShortlistItem, SourceDocument)

    s = purge_all(engine)
    with Session(engine) as db:
        for model in (ShortlistItem, Shortlist, EntityAlias, EntityLink,
                      SourceDocument, AwardFreshness, DeviceBinding, LicenseKey,
                      UsageRecord, Subscription, WebhookEvent, AuditLog, Org):
            for row in db.exec(select(model)).all():
                db.delete(row)
        db.commit()
    _fill_usage(s)
    return s


def maybe_wipe_identities(engine) -> bool:
    """One-shot wipe after switching to email-only. Safe to call on every boot."""
    marker = _resolve(settings.reports_dir).resolve().parent / ".wiped-identities-v8"
    if marker.exists():
        return False
    wipe_identities(engine)
    try:
        marker.write_text("omniscope-8.0.0\n", encoding="utf-8")
    except OSError:
        pass
    return True


def delete_one(engine, report_id: str) -> bool:
    from app.models import Report

    s = Swept()
    with Session(engine) as db:
        r = db.get(Report, report_id)
        if not r:
            return False
        job_id = r.job_id
        _rm_report_files(r, s)
        db.delete(r)
        _delete_job_if_unreferenced(db, job_id, s)
        db.commit()
    return True
