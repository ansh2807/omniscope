"""Entity resolution (spec §23).

Decide whether two surfaces are the same subject using hard identifiers only:

  * exact registrable domain
  * exact platform + handle

A shared display name is never enough to merge or link. That is how
"OpenAI Inc." and a random "OpenAI fan page" stay apart until a domain or
handle overlaps with evidence.

Identifiers carry source + method + confidence so every link is explainable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.engine.discovery.expander import classify as classify_link
from app.engine.resolver import resolve as resolve_social
from app.omni.identity import cin_valid, gstin_valid
from app.omni.webintel import SocialPresence, WebIntelPayload

KIND_DOMAIN = "domain"
KIND_HANDLE = "handle"
KIND_NAME = "name"
KIND_GSTIN = "gstin"
KIND_CIN = "cin"
KIND_LEI = "lei"
HARD_PRINT_KINDS = {KIND_GSTIN, KIND_CIN, KIND_LEI}

# Hosts that appear in bios but are never an organization's own website.
_NON_ENTITY_HOSTS = (
    "wikipedia.org", "linkedin.com", "facebook.com", "instagram.com", "youtube.com",
    "youtu.be", "x.com", "twitter.com", "threads.net", "threads.com", "tiktok.com",
    "crunchbase.com", "glassdoor.", "indeed.", "amazon.", "flipkart.", "justdial.",
    "reddit.com", "quora.com", "medium.com", "substack.com", "github.com",
    "linktr.ee", "beacons.ai", "bio.link", "bit.ly", "t.co", "youtu.be",
)

_NAME_JUNK = re.compile(r"\b(inc|llc|ltd|pvt|private|limited|co|corp|the)\b", re.I)


@dataclass(frozen=True)
class Identifier:
    kind: str
    value: str
    platform: str = ""
    source_url: str = ""
    method: str = ""
    confidence: float = 1.0


@dataclass(frozen=True)
class Match:
    rel: str
    confidence: float
    reason: str
    left: Identifier
    right: Identifier


@dataclass
class CreatorSurface:
    """Minimal creator identity for graph upsert — not a full report payload."""
    name: str
    handle: str
    platform: str
    seed_url: str
    website_domains: list[tuple[str, str]]  # (domain, source_url)
    other_handles: list[tuple[str, str, str]]  # (platform, handle, url)
    score: float | None = None


def normalize_domain(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    host = urlparse(text).netloc.lower().removeprefix("www.")
    return host.split(":")[0]


def normalize_handle(raw: str) -> str:
    return (raw or "").strip().lstrip("@").lower()


def normalize_name(raw: str) -> str:
    text = _NAME_JUNK.sub(" ", (raw or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def is_entity_domain(domain: str) -> bool:
    host = (domain or "").lower()
    if not host or "." not in host:
        return False
    return not any(b in host for b in _NON_ENTITY_HOSTS)


def social_from_url(url: str) -> Identifier | None:
    platform = classify_link(url)
    if not platform or platform == "website":
        return None
    try:
        resolved = resolve_social(url)
    except ValueError:
        return None
    if resolved.platform == "website" or not resolved.handle:
        return None
    return Identifier(
        kind=KIND_HANDLE,
        value=normalize_handle(resolved.handle),
        platform=resolved.platform,
        source_url=url,
        method="url_parse",
        confidence=0.9,
    )


def identifiers_from_web(payload: WebIntelPayload) -> list[Identifier]:
    out: list[Identifier] = []
    domain = (payload.domain or "").lower()
    if domain:
        out.append(Identifier(
            KIND_DOMAIN, domain, source_url=payload.seed_url,
            method="crawl", confidence=1.0))
    if payload.entity_name:
        out.append(Identifier(
            KIND_NAME, normalize_name(payload.entity_name),
            source_url=payload.seed_url, method="page_extract", confidence=0.45))
    for social in payload.socials:
        ident = _social_identifier(social)
        if ident is not None:
            out.append(ident)
    intel = payload.identity_intel or {}
    if hasattr(intel, "model_dump"):
        intel = intel.model_dump()
    for row in (intel.get("ids") or []) if isinstance(intel, dict) else []:
        if not isinstance(row, dict):
            continue
        kind = (row.get("kind") or "").lower()
        value = (row.get("value") or "").strip()
        if kind not in HARD_PRINT_KINDS or not value:
            continue
        if kind == KIND_GSTIN and not gstin_valid(value):
            continue
        if kind == KIND_CIN and not cin_valid(value):
            continue
        out.append(Identifier(
            kind, value.upper(),
            source_url=row.get("url") or payload.seed_url,
            method="printed_id", confidence=0.85))
    return _dedupe(out)


def identifiers_from_creator(surface: CreatorSurface) -> list[Identifier]:
    out: list[Identifier] = []
    handle = normalize_handle(surface.handle)
    platform = (surface.platform or "").lower()
    if handle and platform and platform != "website":
        out.append(Identifier(
            KIND_HANDLE, handle, platform=platform, source_url=surface.seed_url,
            method="seed", confidence=1.0))
    if surface.name:
        out.append(Identifier(
            KIND_NAME, normalize_name(surface.name), source_url=surface.seed_url,
            method="profile", confidence=0.4))
    for plat, other, url in surface.other_handles:
        plat = (plat or "").lower()
        other = normalize_handle(other)
        if other and plat and plat != "website":
            out.append(Identifier(
                KIND_HANDLE, other, platform=plat, source_url=url,
                method="owned_link", confidence=0.85))
    for domain, url in surface.website_domains:
        if is_entity_domain(domain):
            out.append(Identifier(
                KIND_DOMAIN, domain, source_url=url,
                method="owned_link", confidence=0.85))
    return _dedupe(out)


def identifiers_from_input(kind: str, value: str, *, platform: str = "",
                           handle: str = "", domain: str = "") -> list[Identifier]:
    """Identifiers implied by a universal input, before any crawl."""
    printed = (value or "").strip()
    if gstin_valid(printed):
        return [Identifier(KIND_GSTIN, printed.upper().replace(" ", ""),
                           method="input", confidence=1.0)]
    compact = printed.upper().replace(" ", "")
    if cin_valid(compact):
        return [Identifier(KIND_CIN, compact, method="input", confidence=1.0)]
    if kind == "website" and domain:
        return [Identifier(KIND_DOMAIN, domain.lower(), source_url=value,
                           method="input", confidence=1.0)]
    if kind == "creator" and handle and platform and platform != "website":
        return [Identifier(KIND_HANDLE, normalize_handle(handle), platform=platform,
                           source_url=value, method="input", confidence=1.0)]
    if kind == "keyword":
        name = normalize_name(value)
        if name:
            return [Identifier(KIND_NAME, name, method="input", confidence=0.3)]
    return []


def match_identifiers(left: Identifier, right: Identifier) -> Match | None:
    """Hard-identifier match. Name vs anything is never a match."""
    if left.kind == KIND_NAME or right.kind == KIND_NAME:
        return None
    if (left.kind in HARD_PRINT_KINDS and left.kind == right.kind
            and left.value == right.value):
        conf = min(left.confidence, right.confidence)
        return Match("SAME_AS", conf, f"exact {left.kind} {left.value}", left, right)
    if left.kind == KIND_DOMAIN and right.kind == KIND_DOMAIN and left.value == right.value:
        conf = min(left.confidence, right.confidence)
        return Match("SAME_AS", conf, f"exact domain {left.value}", left, right)
    if (left.kind == KIND_HANDLE and right.kind == KIND_HANDLE
            and left.platform == right.platform and left.value == right.value):
        conf = min(left.confidence, right.confidence)
        return Match("HAS_ACCOUNT", conf,
                     f"exact {left.platform} handle @{left.value}", left, right)
    return None


def surface_from_report(payload) -> CreatorSurface:
    """Pull graph identifiers out of a creator ReportPayload."""
    raw = payload.raw
    platform = str(getattr(raw, "seed_platform", "") or "")
    handle = normalize_handle(getattr(raw, "seed_handle", None)
                              or (payload.subject_handle or "").lstrip("@"))
    domains: list[tuple[str, str]] = []
    others: list[tuple[str, str, str]] = []
    for acc in getattr(raw, "accounts", []) or []:
        acc_plat = str(getattr(acc, "platform", "") or "")
        acc_handle = normalize_handle(getattr(acc, "handle", "") or "")
        if acc_handle and acc_plat and acc_plat != "website":
            others.append((acc_plat, acc_handle, getattr(acc, "url", "") or ""))
        for link in getattr(acc, "external_links", []) or []:
            plat = classify_link(link)
            if plat == "website":
                domain = normalize_domain(link)
                if is_entity_domain(domain):
                    domains.append((domain, link))
            elif plat:
                ident = social_from_url(link)
                if ident is not None:
                    others.append((ident.platform, ident.value, link))
    score = None
    mb = getattr(payload, "media_buy", None) or {}
    if isinstance(mb, dict) and mb.get("fit_score") is not None:
        try:
            score = float(mb["fit_score"])
        except (TypeError, ValueError):
            score = None
    if score is None:
        audience = getattr(payload, "audience", None)
        conf = getattr(audience, "overall_confidence", None)
        if conf is not None:
            score = round(float(conf) * 100, 1)
    return CreatorSurface(
        name=payload.subject_name or handle,
        handle=handle,
        platform=platform,
        seed_url=payload.seed_url,
        website_domains=_dedupe_pairs(domains),
        other_handles=_dedupe_triples(others),
        score=score,
    )


def _social_identifier(social: SocialPresence) -> Identifier | None:
    if social.url:
        parsed = social_from_url(social.url)
        if parsed is not None:
            method = "website_link" if not social.error else "website_claim"
            conf = 0.9 if not social.error else 0.7
            return Identifier(KIND_HANDLE, parsed.value, platform=parsed.platform,
                              source_url=social.url, method=method, confidence=conf)
    handle = normalize_handle(social.handle)
    platform = (social.platform or "").lower()
    if handle and platform and platform != "website":
        return Identifier(
            KIND_HANDLE, handle, platform=platform, source_url=social.url,
            method="website_link" if not social.error else "website_claim",
            confidence=0.85 if not social.error else 0.65)
    return None


def _dedupe(items: list[Identifier]) -> list[Identifier]:
    seen: set[tuple[str, str, str]] = set()
    out: list[Identifier] = []
    for item in items:
        key = (item.kind, item.value, item.platform)
        if not item.value or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _dedupe_pairs(rows: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for a, b in rows:
        if a in seen:
            continue
        seen.add(a)
        out.append((a, b))
    return out


def _dedupe_triples(rows: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str]] = []
    for a, b, c in rows:
        key = (a, b)
        if key in seen:
            continue
        seen.add(key)
        out.append((a, b, c))
    return out
