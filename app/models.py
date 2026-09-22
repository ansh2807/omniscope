"""Persistence. SQLite by default; point DATABASE_URL at Postgres for production."""
from __future__ import annotations

import enum
import json
from datetime import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    NEEDS_INPUT = "needs_input"   # leftover gate; new jobs never stop here
    DONE = "done"
    FAILED = "failed"


class Job(SQLModel, table=True):
    id: str = Field(primary_key=True)
    seed_url: str          # first seed; full list lives in seeds_json
    seeds_json: str | None = Field(default=None, sa_column=Column(Text))
    status: str = Field(default=JobStatus.QUEUED.value, index=True)
    stage: str = ""
    progress: int = 0
    error: str | None = Field(default=None, sa_column=Column(Text))
    created_by: str | None = None
    org_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    raw_json: str | None = Field(default=None, sa_column=Column(Text))
    manual_json: str | None = Field(default=None, sa_column=Column(Text))
    recipient_email: str | None = Field(default=None, index=True)
    email_status: str | None = None   # pending | sent | skipped | failed


class Report(SQLModel, table=True):
    id: str = Field(primary_key=True)
    job_id: str = Field(index=True)
    share_slug: str = Field(index=True, unique=True)
    subject_name: str
    subject_handle: str
    seed_url: str
    org_id: str | None = Field(default=None, index=True)
    kind: str = Field(default="single", index=True)   # single | cohort
    subject_count: int = 1
    html_path: str
    docx_path: str | None = None
    payload_json: str | None = Field(default=None, sa_column=Column(Text))
    subjects_json: str | None = Field(default=None, sa_column=Column(Text))
    summary_json: str | None = Field(default=None, sa_column=Column(Text))
    overall_confidence: float = 0.0
    fit_score: float | None = Field(default=None, index=True)
    media_verdict: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    def subjects(self) -> list[dict]:
        """Every subject this report covers, as ``[{name, handle, seed_url}, ...]``.

        One entry for a single report, one per creator for a cohort. This is the join
        key per-creator lookups and erasure must use: on cohort rows subject_name and
        subject_handle are display labels ("A · B · C", "3 creators"), not keys.
        """
        if not self.subjects_json:
            return []
        try:
            data = json.loads(self.subjects_json)
        except ValueError:
            return []
        return data if isinstance(data, list) else []


class Shortlist(SQLModel, table=True):
    """Campaign shortlist — CreatorIQ-style roster for an agency team."""
    id: str = Field(primary_key=True)
    org_id: str | None = Field(default=None, index=True)
    name: str = Field(index=True)
    brief: str = ""
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Entity(SQLModel, table=True):
    """A resolved subject (website or creator surface). Re-runs update this row."""
    id: str = Field(primary_key=True)
    org_id: str | None = Field(default=None, index=True)
    kind: str = Field(default="website", index=True)   # website | creator
    name: str
    domain: str = Field(default="", index=True)
    canonical_url: str = ""
    last_report_id: str | None = Field(default=None, index=True)
    last_score: float | None = None
    snapshot_json: str | None = Field(default=None, sa_column=Column(Text))
    watch_json: str | None = Field(default=None, sa_column=Column(Text))
    watched: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    def snapshot(self) -> dict:
        if not self.snapshot_json:
            return {}
        try:
            data = json.loads(self.snapshot_json)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}


class EntityAlias(SQLModel, table=True):
    """A hard or soft identifier observed for an entity. Soft names never merge."""
    id: str = Field(primary_key=True)
    entity_id: str = Field(index=True)
    org_id: str | None = Field(default=None, index=True)
    kind: str = Field(index=True)          # domain | handle | name
    value: str = Field(index=True)
    platform: str = ""                     # handle only
    source_url: str = ""
    method: str = ""
    confidence: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EntityLink(SQLModel, table=True):
    """Typed, evidenced relationship. Relationships can be added; they are not deleted
    on re-analyze (a vanished social drops the alias, not history)."""
    id: str = Field(primary_key=True)
    org_id: str | None = Field(default=None, index=True)
    from_id: str = Field(index=True)
    to_id: str = Field(index=True)
    rel: str = Field(index=True)            # HAS_ACCOUNT | LINKS_TO | SAME_AS
    evidence: str = ""
    method: str = ""
    confidence: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class EvidenceItem(SQLModel, table=True):
    """Latest-run evidence for an entity. Full history lives on report payloads."""
    id: str = Field(primary_key=True)
    entity_id: str = Field(index=True)
    report_id: str | None = Field(default=None, index=True)
    org_id: str | None = Field(default=None, index=True)
    claim: str
    source_url: str
    method: str = "http_get"
    collected_at: str = ""
    content_sha256: str | None = None


class EntitySnapshot(SQLModel, table=True):
    """One observation of an entity. ORACLE and alerts compare these."""
    id: str = Field(primary_key=True)
    entity_id: str = Field(index=True)
    report_id: str | None = Field(default=None, index=True)
    overall_score: float = 0.0
    tech_json: str = "[]"
    socials_json: str = "[]"
    latest_dated_content: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class Alert(SQLModel, table=True):
    """Change detected on a watched entity after a re-analyze."""
    id: str = Field(primary_key=True)
    org_id: str | None = Field(default=None, index=True)
    entity_id: str = Field(index=True)
    kind: str = Field(index=True)          # score | tech | social | content
    severity: str = Field(default="info")  # info | watch | urgent
    title: str
    detail: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    read: bool = Field(default=False, index=True)


class AwardFreshness(SQLModel, table=True):
    """Last fetch of an official award catalog URL. Dates are observed, not typical seasons."""
    name: str = Field(primary_key=True)
    url: str = ""
    intel_json: str = Field(default="", sa_column=Column(Text))
    fetched_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    status: str = Field(default="", index=True)  # assessed | empty | robots | error


class SourceDocument(SQLModel, table=True):
    """An uploaded public/authorized document used as evidence."""
    id: str = Field(primary_key=True)
    org_id: str | None = Field(default=None, index=True)
    filename: str
    media_type: str = ""
    stored_path: str = ""
    chars: int = 0
    excerpt: str = ""
    intel_json: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    def intel(self) -> dict:
        if not self.intel_json:
            return {}
        try:
            data = json.loads(self.intel_json)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}


class ShortlistItem(SQLModel, table=True):
    id: str = Field(primary_key=True)
    shortlist_id: str = Field(index=True)
    report_id: str | None = Field(default=None, index=True)
    platform: str = ""
    handle: str = ""
    url: str = ""
    display_name: str = ""
    note: str = ""
    status: str = Field(default="shortlisted", index=True)  # shortlisted|outreach|negotiating|won|pass
    fit_score: float | None = None
    media_verdict: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
