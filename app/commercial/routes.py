"""Commercial HTTP surface: signup, billing, licence validation, updates, admin."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.commercial import entitlements as ent_lib
from app.commercial import plans as plan_lib
from app.commercial import razorpay_client as rz
from app.commercial.models import (AppRelease, AuditLog, DeviceBinding, LicenseKey, Mode,
                                   Org, OrgStatus, Plan, Subscription, WebhookEvent,
                                   trial_expiry)
from app.config import settings
from app.db import engine as db_engine
from app.db import get_session

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["app_version"] = settings.app_version

public = APIRouter(tags=["commercial"])
admin = APIRouter(prefix="/admin", tags=["admin"])


# ============================================================== auth helpers
def current_org(request: Request, db: Session) -> Org | None:
    key = (request.headers.get("x-license-key")
           or request.cookies.get("ci_key")
           or request.query_params.get("key", ""))
    if not key:
        return None
    org, _, _ = ent_lib.org_for_key(db, key)
    return org


def require_admin(request: Request) -> str:
    token = (request.headers.get("x-admin-token")
             or request.cookies.get("ci_admin")
             or request.query_params.get("token", ""))
    if not settings.admin_token:
        raise HTTPException(503, "ADMIN_TOKEN is not set — the admin panel is disabled.")
    if not secrets.compare_digest(token, settings.admin_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "admin token required")
    return token


# ================================================================== signup
@public.get("/signup", response_class=HTMLResponse)
def signup_page():
    return RedirectResponse("/", status_code=303)


@public.post("/signup")
def signup():
    return RedirectResponse("/", status_code=303)


# ================================================================== billing
@public.get("/billing", response_class=HTMLResponse)
def billing_page():
    return RedirectResponse("/", status_code=303)


@public.post("/billing/subscribe")
async def subscribe(request: Request, plan_code: str = Form(...),
                    db: Session = Depends(get_session)):
    org = current_org(request, db)
    if not org:
        raise HTTPException(401, "sign in with your licence key first")
    plan = db.get(Plan, plan_code)
    if not plan or not plan.active:
        raise HTTPException(404, "unknown plan")
    if not rz.configured():
        raise HTTPException(503, "Billing is not configured on this server yet.")

    rp_id = plan.razorpay_plan_id or await rz.ensure_plan(plan)
    if not rp_id:
        raise HTTPException(502, "Could not create the plan at Razorpay.")
    if plan.razorpay_plan_id != rp_id:
        plan.razorpay_plan_id = rp_id
        db.add(plan)
        db.commit()

    out = await rz.create_subscription(rp_id, org_id=org.id, email=org.email)
    if not out.get("id"):
        raise HTTPException(502, f"Razorpay: {out.get('error', {}).get('description', 'failed')}")

    sub = Subscription(org_id=org.id, plan_code=plan.code,
                       provider_subscription_id=out["id"], status=out.get("status", "created"),
                       raw=json.dumps(out)[:8000])
    db.add(sub)
    db.commit()
    ent_lib.audit(db, org.email, "subscription.created", org.id, f"{plan.code} {out['id']}")
    # short_url is Razorpay's hosted checkout — no card data ever touches this server
    return RedirectResponse(out.get("short_url") or "/billing", status_code=303)


@public.post("/billing/webhook")
async def razorpay_webhook(request: Request):
    """Signature-verified. Entitlement only ever changes here, never on a redirect."""
    body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    if not rz.verify_webhook(body, signature):
        raise HTTPException(400, "invalid signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid payload")

    event_type = payload.get("event", "")
    event_id = (request.headers.get("x-razorpay-event-id")
                or payload.get("id") or secrets.token_hex(12))

    with Session(db_engine) as db:
        seen = db.exec(select(WebhookEvent)
                       .where(WebhookEvent.event_id == event_id)).first()
        if seen and seen.processed:
            return JSONResponse({"ok": True, "duplicate": True})
        evt = seen or WebhookEvent(event_id=event_id, event_type=event_type,
                                   payload=body.decode("utf-8", "replace")[:20000])
        db.add(evt)
        db.commit()

        try:
            info = rz.interpret(event_type, payload)
            org = None
            if info.get("org_id"):
                org = db.get(Org, info["org_id"])
            if not org and info.get("subscription_id"):
                sub = db.exec(select(Subscription).where(
                    Subscription.provider_subscription_id == info["subscription_id"])).first()
                org = db.get(Org, sub.org_id) if sub else None

            if org:
                sub = db.exec(select(Subscription).where(
                    Subscription.provider_subscription_id == info["subscription_id"])
                ).first() if info.get("subscription_id") else None
                if sub:
                    sub.status = info.get("status") or sub.status
                    sub.current_period_start = info.get("current_start") or sub.current_period_start
                    sub.current_period_end = info.get("current_end") or sub.current_period_end
                    if info.get("org_status") == "cancelled":
                        sub.cancelled_at = datetime.utcnow()
                    db.add(sub)

                new_status = info.get("org_status")
                if new_status:
                    org.status = new_status
                    if new_status == "active" and sub:
                        org.plan_code = sub.plan_code
                    org.updated_at = datetime.utcnow()
                    db.add(org)
                ent_lib.audit(db, "razorpay", f"webhook.{event_type}", org.id,
                              json.dumps(info, default=str)[:900])
            evt.processed = True
            db.add(evt)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            evt.error = f"{type(exc).__name__}: {exc}"
            db.add(evt)
            db.commit()
            raise HTTPException(500, "webhook processing failed") from exc

    return JSONResponse({"ok": True})


# ======================================================= licence + updates
@public.post("/api/license/validate")
def validate_license(payload: dict, request: Request,
                     db: Session = Depends(get_session)):
    """Called by self-hosted instances. Returns the entitlement they should cache."""
    key = (payload.get("key") or "").strip().upper()
    device_id = (payload.get("device_id") or "").strip()[:80]
    version = (payload.get("version") or "").strip()[:24]

    org, row, err = ent_lib.org_for_key(db, key)
    if err or not org or not row:
        return JSONResponse({"valid": False, "reason": err or "unknown key"},
                            status_code=200)

    ent = ent_lib.resolve(db, org)
    if not ent.allow_selfhost and row.mode == Mode.SELFHOST.value:
        return JSONResponse({"valid": False,
                             "reason": ("This plan does not include self-hosting. "
                                        "Upgrade to the Self-hosted plan.")})

    if device_id:
        binding = db.exec(select(DeviceBinding).where(
            DeviceBinding.key == key, DeviceBinding.device_id == device_id)).first()
        if not binding:
            count = len(db.exec(select(DeviceBinding)
                                .where(DeviceBinding.key == key)).all())
            if row.max_devices and count >= row.max_devices:
                return JSONResponse({
                    "valid": False,
                    "reason": (f"This licence is already activated on {count} devices "
                               f"(limit {row.max_devices}). Deactivate one first.")})
            binding = DeviceBinding(key=key, device_id=device_id,
                                    hostname=(payload.get("hostname") or "")[:80],
                                    platform=(payload.get("platform") or "")[:40],
                                    version=version)
        binding.last_seen_at = datetime.utcnow()
        binding.version = version or binding.version
        db.add(binding)

    row.last_seen_at = datetime.utcnow()
    row.last_seen_ip = (request.client.host if request.client else None)
    row.last_seen_version = version or row.last_seen_version
    db.add(row)
    db.commit()

    latest = db.exec(select(AppRelease)
                     .where(AppRelease.channel == settings.update_channel,
                            AppRelease.active == True)  # noqa: E712
                     .order_by(AppRelease.published_at.desc())).first()

    return JSONResponse({
        "valid": ent.allowed or ent.org.status == OrgStatus.PAST_DUE.value,
        "reason": ent.reason,
        "org": {"id": org.id, "name": org.name, "company": org.company},
        "plan": {"code": ent.plan.code, "name": ent.plan.name,
                 "reports_per_month": ent.reports_limit,
                 "max_cohort_size": ent.max_cohort_size,
                 "white_label": ent.allow_white_label},
        "usage": {"period": ent.period, "used": ent.reports_used,
                  "left": ent.reports_left},
        "grace_days": settings.license_grace_days,
        "checked_at": datetime.utcnow().isoformat(),
        "latest_release": ({"version": latest.version, "notes": latest.notes,
                            "download_url": latest.download_url, "sha256": latest.sha256,
                            "mandatory": latest.mandatory} if latest else None),
    })


@public.get("/api/updates/latest")
def latest_release(channel: str = "stable", db: Session = Depends(get_session)):
    rel = db.exec(select(AppRelease)
                  .where(AppRelease.channel == channel, AppRelease.active == True)  # noqa: E712
                  .order_by(AppRelease.published_at.desc())).first()
    if not rel:
        return JSONResponse({"available": False})
    return JSONResponse({
        "available": True, "version": rel.version, "notes": rel.notes,
        "download_url": rel.download_url, "sha256": rel.sha256,
        "mandatory": rel.mandatory, "published_at": rel.published_at.isoformat(),
    })


# =================================================================== admin
@admin.get("/login", response_class=HTMLResponse)
def admin_login(request: Request):
    return templates.TemplateResponse("admin/login.html", {
        "request": request, "app_name": settings.app_name,
        "configured": bool(settings.admin_token),
    })


@admin.post("/login")
def admin_login_post(token: str = Form(...)):
    if not settings.admin_token or not secrets.compare_digest(token, settings.admin_token):
        return RedirectResponse("/admin/login?err=1", status_code=303)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie("ci_admin", token, httponly=True, samesite="lax",
                    max_age=60 * 60 * 12)
    return resp


@admin.get("", response_class=HTMLResponse)
def admin_home(request: Request, db: Session = Depends(get_session),
               _: str = Depends(require_admin)):
    orgs = db.exec(select(Org).order_by(Org.created_at.desc()).limit(200)).all()
    period = ent_lib.current_period()
    from app.commercial.models import UsageRecord
    usage = {u.org_id: u for u in db.exec(
        select(UsageRecord).where(UsageRecord.period == period)).all()}
    plans = {p.code: p for p in db.exec(select(Plan)).all()}

    mrr = 0
    for o in orgs:
        if o.status == OrgStatus.ACTIVE.value:
            mrr += (plans.get(o.plan_code).price_inr if plans.get(o.plan_code) else 0)
    stats = {
        "orgs": len(orgs),
        "active": sum(1 for o in orgs if o.status == OrgStatus.ACTIVE.value),
        "trial": sum(1 for o in orgs if o.status == OrgStatus.TRIAL.value),
        "past_due": sum(1 for o in orgs if o.status == OrgStatus.PAST_DUE.value),
        "mrr": mrr,
        "reports_this_month": sum(u.reports_used for u in usage.values()),
    }
    return templates.TemplateResponse("admin/index.html", {
        "request": request, "app_name": settings.app_name, "orgs": orgs,
        "usage": usage, "plans": plans, "stats": stats, "period": period,
        "razorpay_ready": rz.configured(),
    })


@admin.get("/org/{org_id}", response_class=HTMLResponse)
def admin_org(org_id: str, request: Request, db: Session = Depends(get_session),
              _: str = Depends(require_admin)):
    org = db.get(Org, org_id)
    if not org:
        raise HTTPException(404)
    keys = db.exec(select(LicenseKey).where(LicenseKey.org_id == org_id)).all()
    subs = db.exec(select(Subscription).where(Subscription.org_id == org_id)
                   .order_by(Subscription.created_at.desc())).all()
    devices = db.exec(select(DeviceBinding)
                      .where(DeviceBinding.key.in_([k.key for k in keys] or [""]))).all()
    ent = ent_lib.resolve(db, org)
    plans = db.exec(select(Plan).order_by(Plan.sort_order)).all()
    from app.models import Report
    reports = db.exec(select(Report).where(Report.org_id == org_id)
                      .order_by(Report.created_at.desc()).limit(25)).all()
    return templates.TemplateResponse("admin/org.html", {
        "request": request, "app_name": settings.app_name, "org": org, "keys": keys,
        "subs": subs, "devices": devices, "ent": ent, "plans": plans, "reports": reports,
    })


@admin.post("/org/{org_id}/update")
def admin_org_update(org_id: str, request: Request, plan_code: str = Form(...),
                     status_value: str = Form(...), notes: str = Form(default=""),
                     db: Session = Depends(get_session),
                     token: str = Depends(require_admin)):
    org = db.get(Org, org_id)
    if not org:
        raise HTTPException(404)
    before = f"{org.plan_code}/{org.status}"
    org.plan_code, org.status = plan_code, status_value
    org.notes = notes or org.notes
    org.updated_at = datetime.utcnow()
    db.add(org)
    db.commit()
    ent_lib.audit(db, "admin", "org.update", org_id, f"{before} -> {plan_code}/{status_value}")
    return RedirectResponse(f"/admin/org/{org_id}", status_code=303)


@admin.post("/org/{org_id}/override")
def admin_org_override(org_id: str, days: int = Form(...), reason: str = Form(default=""),
                       db: Session = Depends(get_session),
                       token: str = Depends(require_admin)):
    """Grant access without a payment — pilots, partners, support goodwill."""
    org = db.get(Org, org_id)
    if not org:
        raise HTTPException(404)
    org.override_until = (datetime.utcnow() + timedelta(days=days)) if days > 0 else None
    org.override_reason = reason or None
    db.add(org)
    db.commit()
    ent_lib.audit(db, "admin", "org.override", org_id, f"{days}d — {reason}")
    return RedirectResponse(f"/admin/org/{org_id}", status_code=303)


@admin.post("/org/{org_id}/keys")
def admin_issue_key(org_id: str, label: str = Form(default="Additional"),
                    mode: str = Form(default="saas"), max_devices: int = Form(default=3),
                    db: Session = Depends(get_session),
                    token: str = Depends(require_admin)):
    if not db.get(Org, org_id):
        raise HTTPException(404)
    key = LicenseKey(org_id=org_id, label=label, mode=mode, max_devices=max_devices)
    db.add(key)
    db.commit()
    ent_lib.audit(db, "admin", "key.issue", org_id, f"{key.key} ({mode})")
    return RedirectResponse(f"/admin/org/{org_id}", status_code=303)


@admin.post("/key/{key}/revoke")
def admin_revoke_key(key: str, reason: str = Form(default=""),
                     db: Session = Depends(get_session),
                     token: str = Depends(require_admin)):
    row = db.get(LicenseKey, key)
    if not row:
        raise HTTPException(404)
    row.active = False
    row.revoked_at = datetime.utcnow()
    row.revoke_reason = reason or "revoked by admin"
    db.add(row)
    db.commit()
    ent_lib.audit(db, "admin", "key.revoke", row.org_id, f"{key} — {reason}")
    return RedirectResponse(f"/admin/org/{row.org_id}", status_code=303)


@admin.get("/plans", response_class=HTMLResponse)
def admin_plans(request: Request, db: Session = Depends(get_session),
                _: str = Depends(require_admin)):
    rows = db.exec(select(Plan).order_by(Plan.sort_order)).all()
    return templates.TemplateResponse("admin/plans.html", {
        "request": request, "app_name": settings.app_name, "plans": rows,
        "razorpay_ready": rz.configured(),
    })


@admin.post("/plans/{code}")
def admin_plan_update(code: str, name: str = Form(...), price_inr: int = Form(...),
                      reports_per_month: int = Form(...), seats: int = Form(...),
                      max_cohort_size: int = Form(...), blurb: str = Form(default=""),
                      active: str = Form(default=""),
                      db: Session = Depends(get_session),
                      token: str = Depends(require_admin)):
    plan = db.get(Plan, code)
    if not plan:
        raise HTTPException(404)
    changed_price = plan.price_inr != price_inr
    plan.name, plan.price_inr = name, price_inr
    plan.reports_per_month, plan.seats = reports_per_month, seats
    plan.max_cohort_size, plan.blurb = max_cohort_size, blurb
    plan.active = bool(active)
    if changed_price:
        # Razorpay plans are immutable once created; a price change needs a new one.
        plan.razorpay_plan_id = None
    db.add(plan)
    db.commit()
    ent_lib.audit(db, "admin", "plan.update", code,
                  f"₹{price_inr}/mo, {reports_per_month} reports"
                  + (" (razorpay plan id cleared — will be recreated)" if changed_price else ""))
    return RedirectResponse("/admin/plans", status_code=303)


@admin.get("/releases", response_class=HTMLResponse)
def admin_releases(request: Request, db: Session = Depends(get_session),
                   _: str = Depends(require_admin)):
    rows = db.exec(select(AppRelease).order_by(AppRelease.published_at.desc())).all()
    return templates.TemplateResponse("admin/releases.html", {
        "request": request, "app_name": settings.app_name, "releases": rows,
        "current": settings.app_version,
    })


@admin.post("/releases")
def admin_publish_release(version: str = Form(...), channel: str = Form(default="stable"),
                          download_url: str = Form(default=""), sha256: str = Form(default=""),
                          notes: str = Form(default=""), mandatory: str = Form(default=""),
                          db: Session = Depends(get_session),
                          token: str = Depends(require_admin)):
    """Publishing here is what makes every self-hosted instance offer the update."""
    rel = db.get(AppRelease, version) or AppRelease(version=version)
    rel.channel, rel.download_url, rel.sha256 = channel, download_url, sha256
    rel.notes, rel.mandatory, rel.active = notes, bool(mandatory), True
    rel.published_at = datetime.utcnow()
    db.add(rel)
    db.commit()
    ent_lib.audit(db, "admin", "release.publish", version, f"{channel}, mandatory={bool(mandatory)}")
    return RedirectResponse("/admin/releases", status_code=303)


@admin.post("/releases/{version}/toggle")
def admin_toggle_release(version: str, db: Session = Depends(get_session),
                         token: str = Depends(require_admin)):
    rel = db.get(AppRelease, version)
    if not rel:
        raise HTTPException(404)
    rel.active = not rel.active
    db.add(rel)
    db.commit()
    ent_lib.audit(db, "admin", "release.toggle", version, f"active={rel.active}")
    return RedirectResponse("/admin/releases", status_code=303)


@admin.get("/audit", response_class=HTMLResponse)
def admin_audit(request: Request, db: Session = Depends(get_session),
                _: str = Depends(require_admin)):
    rows = db.exec(select(AuditLog).order_by(AuditLog.at.desc()).limit(300)).all()
    return templates.TemplateResponse("admin/audit.html", {
        "request": request, "app_name": settings.app_name, "rows": rows,
    })
