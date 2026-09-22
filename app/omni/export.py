"""Shareable JSON pack and CSV of stored rows (spec §30, §41).

Packs and tables are what we already persisted. They do not re-run engines or
fill missing measurements.
"""
from __future__ import annotations

import csv
import io
import json

from app.models import Report


def pack_report(report: Report | None) -> dict | None:
    """Return a JSON-ready pack, or None when no payload was stored."""
    if not report or not report.payload_json:
        return None
    try:
        payload = json.loads(report.payload_json)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return {
        "kind": report.kind,
        "slug": report.share_slug,
        "subject": report.subject_name,
        "seed_url": report.seed_url,
        "created_at": report.created_at.isoformat(),
        "payload": payload,
        "note": "Stored evidence only. Missing fields stay missing.",
    }


def rows_to_csv(headers: list[str], rows: list[list[str]]) -> str:
    """RFC-style CSV. Values are already strings; nothing is inferred."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if cell is None else str(cell) for cell in row])
    return buf.getvalue()
