"""Entitlement resolution and quota enforcement.

One function answers the only question that matters at request time: is this org allowed
to generate a report right now, and if not, exactly why. Everything else — plan lookup,
trial expiry, manual overrides, subscription state, usage counting — resolves inside it,
so no caller has to reassemble the rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from app.commercial.models import (AuditLog, LicenseKey, Org, OrgStatus, Plan,
                                   Subscription, UsageRecord)


def current_period() -> str:
    return datetime.utcnow().strftime("%Y-%m")


@dataclass
class Entitlement:
    org: Org
    plan: Plan
    allowed: bool
    reason: str = ""
    reports_used: int = 0
    reports_limit: int = 0
    reports_left: int | None = None      # None = unlimited
    seats: int = 1
    max_cohort_size: int = 4
    allow_selfhost: bool = False
    allow_api: bool = False
    allow_white_label: bool = False
    period: str = ""
    expires_at: datetime | None = None
    upgrade_hint: str = ""

    @property
    def unlimited(self) -> bool:
        return self.reports_limit == 0


def _plan_for(db: Session, code: str) -> Plan:
    plan = db.get(Plan, code)
    if plan:
        return plan
    return db.get(Plan, "trial") or Plan(
        code="trial", name="Trial", price_inr=0, reports_per_month=3, sort_order=0)


def usage_for(db: Session, org_id: str, period: str | None = None) -> UsageRecord:
    period = period or current_period()
    row = db.exec(
        select(UsageRecord).where(UsageRecord.org_id == org_id,
                                  UsageRecord.period == period)).first()
    if not row:
        row = UsageRecord(org_id=org_id, period=period)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def resolve(db: Session, org: Org, *, period: str | None = None) -> Entitlement:
    """Work out what this org may do right now, and why."""
    period = period or current_period()
    plan = _plan_for(db, org.plan_code)
    usage = usage_for(db, org.id, period)
    now = datetime.utcnow()

    ent = Entitlement(
        org=org, plan=plan, allowed=False,
        reports_used=usage.reports_used,
        reports_limit=plan.reports_per_month,
        reports_left=(None if plan.reports_per_month == 0
                      else max(0, plan.reports_per_month - usage.reports_used)),
        seats=plan.seats, max_cohort_size=plan.max_cohort_size,
        allow_selfhost=plan.allow_selfhost, allow_api=plan.allow_api,
        allow_white_label=plan.allow_white_label, period=period,
    )

    # 1. A manual override always wins — pilots, partners, support goodwill.
    if org.override_until and org.override_until > now:
        ent.allowed = True
        ent.expires_at = org.override_until
        ent.reason = (f"Manual override active until "
                      f"{org.override_until:%d %b %Y}"
                      + (f" — {org.override_reason}" if org.override_reason else ""))
        return ent

    # 2. Hard stops.
    if org.status == OrgStatus.SUSPENDED.value:
        ent.reason = ("This account is suspended. Contact support — no reports can be "
                      "generated until it is reinstated.")
        return ent
    if org.status == OrgStatus.CANCELLED.value:
        ent.reason = ("This subscription was cancelled. Resubscribe to generate reports "
                      "again; existing reports remain accessible.")
        ent.upgrade_hint = "resubscribe"
        return ent

    # 3. Trial window.
    if org.status == OrgStatus.TRIAL.value:
        if org.trial_ends_at and org.trial_ends_at < now:
            ent.reason = (f"The trial ended on {org.trial_ends_at:%d %b %Y}. "
                          f"Choose a plan to continue.")
            ent.upgrade_hint = "trial_expired"
            return ent
        ent.expires_at = org.trial_ends_at

    # 4. Payment failure — kept usable briefly rather than cut off instantly, because a
    #    failed mandate is usually a bank issue rather than an intent to stop paying.
    if org.status == OrgStatus.PAST_DUE.value:
        sub = db.exec(
            select(Subscription).where(Subscription.org_id == org.id)
            .order_by(Subscription.created_at.desc())).first()
        grace_end = sub.current_period_end if sub and sub.current_period_end else None
        if grace_end and (now - grace_end).days > 7:
            ent.reason = ("Payment has been failing for more than a week. Update your "
                          "payment method to restore access.")
            ent.upgrade_hint = "payment_failed"
            return ent
        ent.reason = "Payment failed — please update your payment method."

    # 5. Quota.
    if plan.reports_per_month and usage.reports_used >= plan.reports_per_month:
        ent.reason = (f"You have used all {plan.reports_per_month} reports on the "
                      f"{plan.name} plan this month. The allowance resets on the 1st.")
        ent.upgrade_hint = "quota_exceeded"
        return ent

    ent.allowed = True
    if not ent.reason:
        ent.reason = "OK"
    return ent


def consume(db: Session, org: Org, *, creators: int = 1,
            period: str | None = None) -> UsageRecord:
    """Record one generated report. Called after a report is successfully produced."""
    usage = usage_for(db, org.id, period)
    usage.reports_used += 1
    usage.creators_profiled += max(1, creators)
    usage.last_report_at = datetime.utcnow()
    db.add(usage)
    db.commit()
    db.refresh(usage)
    return usage


def org_for_key(db: Session, key: str) -> tuple[Org | None, LicenseKey | None, str]:
    """Resolve a licence key to its org. Returns (org, key_row, error_message)."""
    if not key:
        return None, None, "No licence key supplied."
    row = db.get(LicenseKey, key.strip().upper())
    if not row:
        return None, None, "That licence key was not recognised."
    if not row.active or row.revoked_at:
        return None, row, (f"This licence key was revoked"
                           + (f" — {row.revoke_reason}" if row.revoke_reason else "") + ".")
    org = db.get(Org, row.org_id)
    if not org:
        return None, row, "The account behind this key no longer exists."
    return org, row, ""


def audit(db: Session, actor: str, action: str, target: str | None = None,
          detail: str | None = None) -> None:
    db.add(AuditLog(actor=actor, action=action, target=target, detail=detail))
    db.commit()
