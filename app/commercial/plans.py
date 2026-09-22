"""Plan catalogue.

Priced against the real marginal cost of a report, which is dominated by the browser
tier (RAM and time) and any search queries. Everything is monthly INR; Razorpay handles
the recurring mandate.

Seeded into the database on first boot and editable from the admin panel afterwards, so
changing a price does not need a deploy.
"""
from __future__ import annotations

DEFAULT_PLANS: list[dict] = [
    {
        "code": "trial", "name": "Trial", "price_inr": 0,
        "reports_per_month": 3, "seats": 1, "max_cohort_size": 2,
        "allow_selfhost": False, "allow_api": False, "allow_white_label": False,
        "sort_order": 0,
        "blurb": "Three reports so you can judge the output before paying for it.",
    },
    {
        "code": "solo", "name": "Solo", "price_inr": 1499,
        "reports_per_month": 25, "seats": 1, "max_cohort_size": 4,
        "allow_selfhost": False, "allow_api": False, "allow_white_label": False,
        "sort_order": 1,
        "blurb": "For a freelancer or a single strategist. 25 reports a month.",
    },
    {
        "code": "agency", "name": "Agency", "price_inr": 4999,
        "reports_per_month": 120, "seats": 5, "max_cohort_size": 8,
        "allow_selfhost": False, "allow_api": True, "allow_white_label": True,
        "sort_order": 2,
        "blurb": "Five seats, 120 reports, API access and your own branding on the output.",
    },
    {
        "code": "selfhost", "name": "Self-hosted", "price_inr": 9999,
        "reports_per_month": 0, "seats": 25, "max_cohort_size": 12,
        "allow_selfhost": True, "allow_api": True, "allow_white_label": True,
        "sort_order": 3,
        "blurb": ("Runs on your own machines and your own IPs, so collection is not "
                  "rate-limited by a shared datacentre address. Unlimited reports, "
                  "auto-updates, licence-key activation on up to 25 devices."),
    },
]


def seed(engine) -> int:
    """Insert any missing plans. Never overwrites a price an admin has changed."""
    from sqlmodel import Session, select

    from app.commercial.models import Plan

    added = 0
    with Session(engine) as s:
        existing = {p.code for p in s.exec(select(Plan)).all()}
        for spec in DEFAULT_PLANS:
            if spec["code"] in existing:
                continue
            s.add(Plan(**spec))
            added += 1
        if added:
            s.commit()
    return added
