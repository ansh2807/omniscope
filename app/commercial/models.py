"""Commercial data model — tenants, licence keys, plans, subscriptions, usage.

Deployment modes share this schema:

  * **SaaS**   — the org lives here, the licence key is the login credential, and the
                 subscription is managed by Razorpay.
  * **Self-host** — the customer runs their own instance; it phones this server to
                 validate its licence key and to learn about updates. The org row here
                 is the source of truth, their instance only caches an entitlement.

Everything is org-scoped. A report belongs to exactly one org, and the quota check runs
against that org's plan before any collection begins.
"""
from __future__ import annotations

import enum
import secrets
from datetime import datetime, timedelta

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class OrgStatus(str, enum.Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class Mode(str, enum.Enum):
    SAAS = "saas"
    SELFHOST = "selfhost"


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def new_license_key() -> str:
    """Human-transcribable licence key: CI-XXXX-XXXX-XXXX-XXXX.

    Uses an unambiguous alphabet — no O/0, I/1/L — because these get read down phones
    and typed off invoices.
    """
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4)]
    return "CI-" + "-".join(groups)


class Org(SQLModel, table=True):
    __tablename__ = "org"
    id: str = Field(default_factory=lambda: new_id("org"), primary_key=True)
    name: str
    email: str = Field(index=True)
    phone: str | None = None
    company: str | None = None
    gstin: str | None = None
    mode: str = Field(default=Mode.SAAS.value, index=True)
    status: str = Field(default=OrgStatus.TRIAL.value, index=True)
    plan_code: str = Field(default="trial", index=True)
    trial_ends_at: datetime | None = None
    notes: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Manual override — lets an admin grant access without a payment, for pilots,
    # partners and support cases. Always wins over the subscription state.
    override_until: datetime | None = None
    override_reason: str | None = None


class LicenseKey(SQLModel, table=True):
    __tablename__ = "license_key"
    key: str = Field(default_factory=new_license_key, primary_key=True)
    org_id: str = Field(index=True, foreign_key="org.id")
    label: str = ""
    mode: str = Field(default=Mode.SAAS.value)
    active: bool = Field(default=True, index=True)
    max_devices: int = 3
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime | None = None
    last_seen_ip: str | None = None
    last_seen_version: str | None = None
    revoked_at: datetime | None = None
    revoke_reason: str | None = None


class DeviceBinding(SQLModel, table=True):
    """Which machines a self-hosted licence has been activated on."""
    __tablename__ = "device_binding"
    id: str = Field(default_factory=lambda: new_id("dev"), primary_key=True)
    key: str = Field(index=True, foreign_key="license_key.key")
    device_id: str = Field(index=True)
    hostname: str | None = None
    platform: str | None = None
    first_seen_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)
    version: str | None = None


class Plan(SQLModel, table=True):
    __tablename__ = "plan"
    code: str = Field(primary_key=True)
    name: str
    price_inr: int                          # per month, in whole rupees
    reports_per_month: int                  # 0 = unlimited
    seats: int = 1
    max_cohort_size: int = 4
    allow_selfhost: bool = False
    allow_api: bool = False
    allow_white_label: bool = False
    razorpay_plan_id: str | None = None
    active: bool = True
    sort_order: int = 0
    blurb: str = ""


class Subscription(SQLModel, table=True):
    __tablename__ = "subscription"
    id: str = Field(default_factory=lambda: new_id("sub"), primary_key=True)
    org_id: str = Field(index=True, foreign_key="org.id")
    plan_code: str
    provider: str = "razorpay"
    provider_subscription_id: str | None = Field(default=None, index=True)
    provider_customer_id: str | None = None
    status: str = Field(default="created", index=True)
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancelled_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    raw: str | None = Field(default=None, sa_column=Column(Text))


class UsageRecord(SQLModel, table=True):
    """One row per org per billing period. Incremented as reports are generated."""
    __tablename__ = "usage_record"
    id: str = Field(default_factory=lambda: new_id("use"), primary_key=True)
    org_id: str = Field(index=True, foreign_key="org.id")
    period: str = Field(index=True)          # YYYY-MM
    reports_used: int = 0
    creators_profiled: int = 0
    last_report_at: datetime | None = None


class WebhookEvent(SQLModel, table=True):
    """Every provider webhook, stored before processing so replays are idempotent."""
    __tablename__ = "webhook_event"
    id: str = Field(default_factory=lambda: new_id("evt"), primary_key=True)
    provider: str = "razorpay"
    event_id: str = Field(index=True, unique=True)
    event_type: str = Field(index=True)
    processed: bool = Field(default=False, index=True)
    error: str | None = Field(default=None, sa_column=Column(Text))
    payload: str | None = Field(default=None, sa_column=Column(Text))
    received_at: datetime = Field(default_factory=datetime.utcnow)


class AppRelease(SQLModel, table=True):
    """What self-hosted instances check against when they phone home."""
    __tablename__ = "app_release"
    version: str = Field(primary_key=True)          # semver, e.g. 2.1.0
    channel: str = Field(default="stable", index=True)
    download_url: str = ""
    sha256: str = ""
    notes: str = Field(default="", sa_column=Column(Text))
    mandatory: bool = False
    min_supported_version: str | None = None
    published_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    active: bool = True


class AuditLog(SQLModel, table=True):
    """Admin actions. Required for any billing dispute, and cheap to keep."""
    __tablename__ = "audit_log"
    id: str = Field(default_factory=lambda: new_id("aud"), primary_key=True)
    actor: str
    action: str = Field(index=True)
    target: str | None = None
    detail: str | None = Field(default=None, sa_column=Column(Text))
    at: datetime = Field(default_factory=datetime.utcnow, index=True)


def trial_expiry(days: int = 7) -> datetime:
    return datetime.utcnow() + timedelta(days=days)
