"""Cross-entity mentions from stored payloads (spec §23, §24).

A mention is a *domain* or printed GSTIN/CIN already on another stored
entity appearing in this subject's competitor list, market map, or news
text. Names never count.
"""
from __future__ import annotations

from urllib.parse import urlparse

from pydantic import BaseModel
from sqlmodel import Session, select

from app.models import Entity, Report
from app.omni.hubs import latest_web_payloads


class MentionRow(BaseModel):
    subject: str
    subject_domain: str = ""
    mentioned: str
    mentioned_domain: str
    via: str                 # competitor | market | news
    evidence: str = ""
    href: str = ""
    mentioned_href: str = ""


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def from_payloads(payloads: list[tuple[Report, dict]],
                  entities: list[Entity]) -> list[MentionRow]:
    """Pure over stored reports + stored domains."""
    by_domain: dict[str, Entity] = {}
    for ent in entities:
        domain = (ent.domain or "").lower().removeprefix("www.")
        if domain:
            by_domain[domain] = ent
    by_id: dict[str, Entity] = {}
    for _report, other in payloads:
        domain = (other.get("domain") or "").lower().removeprefix("www.")
        ent = by_domain.get(domain)
        if ent is None:
            continue
        for item in (other.get("identity_intel") or {}).get("ids") or []:
            if not isinstance(item, dict):
                continue
            kind = (item.get("kind") or "").lower()
            value = (item.get("value") or "").strip().upper()
            if kind in {"gstin", "cin"} and value:
                by_id[value] = ent
    rows: list[MentionRow] = []
    for report, data in payloads:
        subject = data.get("entity_name") or report.subject_name
        subject_domain = (data.get("domain") or "").lower().removeprefix("www.")
        href = f"/r/{report.share_slug}"

        def hit(domain: str, via: str, evidence: str) -> None:
            domain = (domain or "").lower().removeprefix("www.")
            if not domain or domain == subject_domain or domain not in by_domain:
                return
            other = by_domain[domain]
            rows.append(MentionRow(
                subject=subject,
                subject_domain=subject_domain,
                mentioned=other.name,
                mentioned_domain=domain,
                via=via,
                evidence=evidence[:180],
                href=href,
                mentioned_href=f"/entities/{other.id}",
            ))

        def hit_printed_ids(blob: str, via: str, evidence: str) -> None:
            text = (blob or "").upper()
            for ident, ent in by_id.items():
                other_domain = (ent.domain or "").lower().removeprefix("www.")
                if ident and ident in text and other_domain != subject_domain:
                    hit(other_domain, via, evidence)

        for rival in (data.get("competitor_intel") or {}).get("competitors") or []:
            if not isinstance(rival, dict):
                continue
            evidence = rival.get("snippet") or rival.get("name") or ""
            hit(rival.get("domain") or _host(rival.get("url") or ""),
                "competitor", evidence)
            hit_printed_ids(" ".join([evidence, rival.get("name") or ""]),
                            "competitor", evidence)
        for part in (data.get("market_intel") or {}).get("participants") or []:
            if not isinstance(part, dict):
                continue
            evidence = part.get("name") or ""
            hit(part.get("domain") or _host(part.get("url") or ""),
                "market", evidence)
            hit_printed_ids(" ".join([evidence, part.get("snippet") or ""]),
                            "market", evidence)
        for item in (data.get("news_intel") or {}).get("items") or []:
            if not isinstance(item, dict):
                continue
            blob = " ".join([
                item.get("title") or "",
                item.get("snippet") or "",
                item.get("excerpt") or "",
                item.get("url") or "",
            ]).lower()
            for domain in by_domain:
                if domain != subject_domain and domain in blob:
                    hit(domain, "news", item.get("title") or item.get("url") or "")
            hit_printed_ids(blob, "news", item.get("title") or item.get("url") or "")
    # Dedupe subject+mentioned+via
    seen: set[tuple[str, str, str]] = set()
    unique: list[MentionRow] = []
    for row in rows:
        key = (row.subject_domain, row.mentioned_domain, row.via)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique[:80]


def mention_rows(session: Session, org_id: str | None) -> list[MentionRow]:
    query = select(Entity)
    if org_id is not None:
        query = query.where(Entity.org_id == org_id)
    else:
        query = query.where(Entity.org_id == None)  # noqa: E711
    entities = list(session.exec(query).all())
    return from_payloads(latest_web_payloads(session, org_id), entities)
