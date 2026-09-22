"""Razorpay integration — subscriptions, checkout and webhooks.

Razorpay rather than Stripe because the customers are Indian: UPI mandates, netbanking
and INR-native settlement all matter more here than Stripe's developer experience.

Two rules enforced throughout, both learned the hard way by everyone who ships billing:

  1. **Never trust a client-side callback.** Entitlement changes only on a
     signature-verified webhook, never on a browser redirect.
  2. **Every webhook is stored before it is processed**, keyed on the provider event id,
     so replays and retries are idempotent.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

from app.config import settings
from app.engine.http import fetch

API = "https://api.razorpay.com/v1"


def configured() -> bool:
    return bool(settings.razorpay_key_id and settings.razorpay_key_secret)


def _auth_header() -> dict[str, str]:
    token = base64.b64encode(
        f"{settings.razorpay_key_id}:{settings.razorpay_key_secret}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


async def _post(path: str, body: dict) -> dict:
    r = await fetch(f"{API}{path}", method="POST", json_body=body,
                    headers=_auth_header(), check_robots=False, use_cache=False)
    try:
        return json.loads(r.text)
    except json.JSONDecodeError:
        return {"error": {"description": f"non-JSON response (status {r.status})"}}


async def _get(path: str) -> dict:
    r = await fetch(f"{API}{path}", headers=_auth_header(),
                    check_robots=False, use_cache=False)
    try:
        return json.loads(r.text)
    except json.JSONDecodeError:
        return {"error": {"description": f"non-JSON response (status {r.status})"}}


# ----------------------------------------------------------------- plan sync
async def ensure_plan(plan) -> str | None:
    """Create the plan at Razorpay if it does not have an id yet. Returns the id."""
    if plan.razorpay_plan_id:
        return plan.razorpay_plan_id
    if not configured() or plan.price_inr <= 0:
        return None
    out = await _post("/plans", {
        "period": "monthly", "interval": 1,
        "item": {
            "name": f"OMNISCOPE — {plan.name}",
            "amount": plan.price_inr * 100,          # paise
            "currency": "INR",
            "description": plan.blurb[:255] or plan.name,
        },
        "notes": {"plan_code": plan.code},
    })
    return out.get("id")


# -------------------------------------------------------------- subscriptions
async def create_subscription(plan_razorpay_id: str, *, org_id: str, email: str,
                              total_count: int = 120) -> dict:
    """A subscription Razorpay will bill monthly. total_count caps the mandate length."""
    return await _post("/subscriptions", {
        "plan_id": plan_razorpay_id,
        "total_count": total_count,
        "quantity": 1,
        "customer_notify": 1,
        "notes": {"org_id": org_id, "email": email},
    })


async def fetch_subscription(sub_id: str) -> dict:
    return await _get(f"/subscriptions/{sub_id}")


async def cancel_subscription(sub_id: str, *, at_cycle_end: bool = True) -> dict:
    return await _post(f"/subscriptions/{sub_id}/cancel",
                       {"cancel_at_cycle_end": 1 if at_cycle_end else 0})


# ------------------------------------------------------------------ webhooks
def verify_webhook(body: bytes, signature: str) -> bool:
    """HMAC-SHA256 over the raw body with the webhook secret. Constant-time compare."""
    secret = settings.razorpay_webhook_secret
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """For one-off checkout callbacks. Still never the source of entitlement truth."""
    secret = settings.razorpay_key_secret
    if not secret:
        return False
    expected = hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _ts(value: Any) -> datetime | None:
    try:
        return datetime.utcfromtimestamp(int(value)) if value else None
    except (TypeError, ValueError):
        return None


# Which Razorpay events move an org between states.
EVENT_MAP = {
    "subscription.activated": "active",
    "subscription.charged": "active",
    "subscription.completed": "cancelled",
    "subscription.cancelled": "cancelled",
    "subscription.paused": "suspended",
    "subscription.resumed": "active",
    "subscription.halted": "past_due",
    "subscription.pending": "past_due",
    "payment.failed": "past_due",
}


def interpret(event_type: str, payload: dict) -> dict:
    """Flatten a Razorpay webhook into the fields we actually act on."""
    entity = {}
    for key in ("subscription", "payment", "order"):
        node = (payload.get("payload", {}) or {}).get(key, {}) or {}
        if node.get("entity"):
            entity = node["entity"]
            break
    notes = entity.get("notes") or {}
    return {
        "org_id": notes.get("org_id"),
        "plan_code": notes.get("plan_code"),
        "subscription_id": entity.get("id") if event_type.startswith("subscription")
        else entity.get("subscription_id"),
        "customer_id": entity.get("customer_id"),
        "status": entity.get("status"),
        "org_status": EVENT_MAP.get(event_type),
        "current_start": _ts(entity.get("current_start")),
        "current_end": _ts(entity.get("current_end")),
        "amount": entity.get("amount"),
    }
