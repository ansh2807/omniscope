"""Per-job search credentials. Never written to settings, disk, or the job row."""
from __future__ import annotations

from contextvars import ContextVar, Token

from app.config import settings

_guest_serper: ContextVar[str] = ContextVar("guest_serper", default="")


def bind_serper_key(key: str) -> Token[str]:
    return _guest_serper.set((key or "").strip())


def reset_serper_key(token: Token[str]) -> None:
    _guest_serper.reset(token)


def guest_serper_key() -> str:
    return _guest_serper.get()


def active_serper_key() -> str:
    return guest_serper_key() or (settings.serper_api_key or "").strip()


def normalize_serper_key(raw: str) -> str:
    key = (raw or "").strip()
    if len(key) < 12 or len(key) > 200:
        return ""
    if any(ch.isspace() for ch in key):
        return ""
    return key
