"""Optional desk prose. The brief is complete without a key.

When OPENAI_API_KEY is set, a short narrative restates already-filled DESK
cells. Numbers that are not in the desk JSON are rejected. A failed or empty
call leaves narrative blank — the deterministic desk is the fallback.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from app.config import settings

_log = logging.getLogger("creatorintel.llm")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_BANNED = (
    "tam", "market share", "sessions/month", "pageviews/month",
    "keyword volume", "unique reach",
)

SYSTEM = (
    "You restate a marketing desk that was already filled from public evidence. "
    "Use only the JSON fields given. If a field is unavailable, say it is "
    "unavailable. Do not invent traffic, TAM, demographics, follower counts, "
    "ad spend, valuations, or any number that is not in the JSON. "
    "Write 3 short paragraphs. No bullet list of invented metrics."
)


def configured() -> bool:
    return bool((settings.openai_api_key or "").strip())


def source_tokens(desk: dict) -> set[str]:
    """Normalised number tokens already present on the desk."""
    blob = json.dumps(desk, ensure_ascii=False)
    return {token.replace(",", "") for token in _NUM.findall(blob)}


def invented_numbers(prose: str, desk: dict) -> list[str]:
    """Numbers in prose that do not appear in the desk JSON."""
    allowed = source_tokens(desk)
    bad: list[str] = []
    for token in _NUM.findall(prose or ""):
        key = token.replace(",", "")
        if key in {"0", "1", "2", "3", "4", "5", "6", "7", "8", "24", "100"}:
            continue
        if key not in allowed:
            bad.append(token)
    return bad


def _sanitize_desk(desk: dict) -> dict:
    """Drop narrative so the model cannot echo a previous invention."""
    copy = dict(desk)
    copy.pop("narrative", None)
    copy.pop("llm_used", None)
    return copy


def narrate_desk(desk: dict | None) -> str:
    """Return prose or empty. Never invent; empty is the deterministic fallback."""
    if not configured() or not isinstance(desk, dict):
        return ""
    payload = _sanitize_desk(desk)
    if not (payload.get("one_liner") or payload.get("job") or payload.get("needs")):
        return ""
    body = {
        "model": (settings.openai_model or "gpt-4o-mini").strip(),
        "temperature": 0.2,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)[:12000]},
        ],
    }
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key.strip()}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=20, trust_env=False) as client:
            resp = client.post(url, headers=headers, json=body)
    except Exception:
        _log.warning("desk narrative request failed", exc_info=True)
        return ""
    if resp.status_code >= 400:
        _log.warning("desk narrative HTTP %s", resp.status_code)
        return ""
    try:
        packed = resp.json()
    except ValueError:
        return ""
    choices = packed.get("choices") if isinstance(packed, dict) else None
    if not isinstance(choices, list) or not choices:
        return ""
    message = (choices[0] or {}).get("message") if isinstance(choices[0], dict) else {}
    text = str((message or {}).get("content") or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if any(token in lowered for token in _BANNED):
        return ""
    if invented_numbers(text, payload):
        return ""
    return text[:1600]
