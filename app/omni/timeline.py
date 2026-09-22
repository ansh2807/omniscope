"""Temporal intelligence from stored observations (spec §24, §33).

A timeline event is something we persisted: a snapshot, an alert, or a news
item already on a report payload. Nothing is backfilled or interpolated.
"""
from __future__ import annotations

import json

from pydantic import BaseModel
from sqlmodel import Session, select

from app.models import Alert, Entity, EntitySnapshot, Report


class TimelineEvent(BaseModel):
    at: str
    kind: str          # snapshot | alert | news
    title: str
    detail: str = ""
    href: str = ""
    severity: str = ""
    entity_id: str = ""
    entity_name: str = ""


def _payload_dict(report: Report | None) -> dict:
    if not report or not report.payload_json:
        return {}
    try:
        data = json.loads(report.payload_json)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def brief_from_report(report: Report | None) -> list[str]:
    """Restated findings already on the last report. Never invents a metric."""
    reasoning = _payload_dict(report).get("reasoning") or {}
    findings = reasoning.get("findings") if isinstance(reasoning, dict) else None
    if not isinstance(findings, list):
        return []
    return [str(item) for item in findings if item][:6]


def from_stores(session: Session, entity_id: str, *,
                report: Report | None = None) -> list[TimelineEvent]:
    """Assemble a timeline. Pure over already-loaded rows plus optional payload."""
    events: list[TimelineEvent] = []
    for snap in session.exec(
            select(EntitySnapshot).where(EntitySnapshot.entity_id == entity_id)
            .order_by(EntitySnapshot.created_at.desc())).all()[:24]:
        href = ""
        if report and snap.report_id == report.id:
            href = f"/r/{report.share_slug}"
        events.append(TimelineEvent(
            at=snap.created_at.isoformat(),
            kind="snapshot",
            title=f"Score {snap.overall_score}",
            detail="stored observation",
            href=href,
            entity_id=entity_id,
        ))
    for alert in session.exec(
            select(Alert).where(Alert.entity_id == entity_id)
            .order_by(Alert.created_at.desc())).all()[:24]:
        events.append(TimelineEvent(
            at=alert.created_at.isoformat(),
            kind="alert",
            title=alert.title,
            detail=alert.detail,
            severity=alert.severity,
            entity_id=entity_id,
        ))
    if report:
        news = (_payload_dict(report).get("news_intel") or {}).get("items") or []
        for item in news[:8]:
            if not isinstance(item, dict):
                continue
            events.append(TimelineEvent(
                at=report.created_at.isoformat(),
                kind="news",
                title=item.get("title") or item.get("narrative") or "news",
                detail=item.get("narrative") or "",
                href=item.get("url") or "",
                entity_id=entity_id,
            ))
        feeds = (_payload_dict(report).get("feed_intel") or {}).get("items") or []
        for item in feeds[:8]:
            if not isinstance(item, dict):
                continue
            if not item.get("title") and not item.get("url"):
                continue
            events.append(TimelineEvent(
                at=item.get("published") or report.created_at.isoformat(),
                kind="feed",
                title=item.get("title") or item.get("url") or "feed",
                detail="first-party feed",
                href=item.get("url") or "",
                entity_id=entity_id,
            ))
        for item in (_payload_dict(report).get("schema_intel") or {}).get("events") or []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            events.append(TimelineEvent(
                at=item.get("start") or report.created_at.isoformat(),
                kind="event",
                title=item.get("name") or "event",
                detail=item.get("location") or "schema Event",
                href=item.get("url") or "",
                entity_id=entity_id,
            ))
        for item in (_payload_dict(report).get("schema_intel") or {}).get("articles") or []:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            published = (item.get("published") or "")[:10]
            modified = (item.get("modified") or "")[:10]
            if published:
                events.append(TimelineEvent(
                    at=published,
                    kind="article",
                    title=item["title"],
                    detail="schema Article/BlogPosting datePublished",
                    href=item.get("url") or "",
                    entity_id=entity_id,
                ))
            if modified and modified != published:
                events.append(TimelineEvent(
                    at=modified,
                    kind="article",
                    title=item["title"],
                    detail="printed dateModified (not a verified edit)",
                    href=item.get("url") or "",
                    entity_id=entity_id,
                ))
        for item in (_payload_dict(report).get("schema_intel") or {}).get("courses") or []:
            if not isinstance(item, dict) or not item.get("name") or not item.get("start"):
                continue
            events.append(TimelineEvent(
                at=item["start"],
                kind="course",
                title=item["name"],
                detail="printed Course startDate (not enrollment)",
                href=item.get("url") or "",
                entity_id=entity_id,
            ))
        for item in (_payload_dict(report).get("review_intel") or {}).get("items") or []:
            if not isinstance(item, dict) or not item.get("published"):
                continue
            events.append(TimelineEvent(
                at=item["published"],
                kind="review",
                title=(item.get("author") or item.get("body") or "review")[:80],
                detail="printed Review datePublished (not a verified review event)",
                href=item.get("source_url") or "",
                entity_id=entity_id,
            ))
        for item in (_payload_dict(report).get("schema_intel") or {}).get("hours") or []:
            if not isinstance(item, dict) or not item.get("valid_through"):
                continue
            events.append(TimelineEvent(
                at=item["valid_through"],
                kind="hours",
                title=item.get("day") or item.get("name") or "hours",
                detail="printed OpeningHoursSpecification validThrough (not open-now)",
                href=item.get("url") or "",
                entity_id=entity_id,
            ))
        for item in (_payload_dict(report).get("schema_intel") or {}).get("web_pages") or []:
            if not isinstance(item, dict) or not item.get("last_reviewed"):
                continue
            events.append(TimelineEvent(
                at=item["last_reviewed"],
                kind="webpage",
                title=item.get("name") or item.get("kind") or "webpage",
                detail="printed lastReviewed (not a verified edit)",
                href=item.get("url") or "",
                entity_id=entity_id,
            ))
        for item in (_payload_dict(report).get("schema_intel") or {}).get("videos") or []:
            if not isinstance(item, dict) or not item.get("title") or not item.get("uploaded"):
                continue
            events.append(TimelineEvent(
                at=item["uploaded"],
                kind="video",
                title=item["title"],
                detail="schema VideoObject uploadDate",
                href=item.get("url") or "",
                entity_id=entity_id,
            ))
        for item in (_payload_dict(report).get("legal_intel") or {}).get("policies") or []:
            if not isinstance(item, dict) or not item.get("updated"):
                continue
            events.append(TimelineEvent(
                at=item["updated"],
                kind="legal",
                title=f"{item.get('kind') or 'policy'} updated",
                detail=item.get("title") or "sampled policy page",
                href=item.get("url") or "",
                entity_id=entity_id,
            ))
    events.sort(key=lambda e: e.at, reverse=True)
    return events[:40]


def tenant_timeline(session: Session, org_id: str | None, *,
                    limit: int = 40) -> list[TimelineEvent]:
    """Tenant-wide events from stored snapshots and alerts. No interpolation."""
    entity_query = select(Entity)
    alert_query = select(Alert)
    if org_id is not None:
        entity_query = entity_query.where(Entity.org_id == org_id)
        alert_query = alert_query.where(Alert.org_id == org_id)
    else:
        entity_query = entity_query.where(Entity.org_id == None)  # noqa: E711
        alert_query = alert_query.where(Alert.org_id == None)  # noqa: E711
    entities = {e.id: e for e in session.exec(entity_query).all()}
    events: list[TimelineEvent] = []
    if entities:
        for snap in session.exec(
                select(EntitySnapshot)
                .where(EntitySnapshot.entity_id.in_(list(entities)))
                .order_by(EntitySnapshot.created_at.desc())).all()[:limit]:
            ent = entities.get(snap.entity_id)
            events.append(TimelineEvent(
                at=snap.created_at.isoformat(),
                kind="snapshot",
                title=f"Score {snap.overall_score}",
                detail="stored observation",
                href=f"/entities/{snap.entity_id}",
                entity_id=snap.entity_id,
                entity_name=ent.name if ent else snap.entity_id,
            ))
    for alert in session.exec(
            alert_query.order_by(Alert.created_at.desc())).all()[:limit]:
        ent = entities.get(alert.entity_id)
        events.append(TimelineEvent(
            at=alert.created_at.isoformat(),
            kind="alert",
            title=alert.title,
            detail=alert.detail,
            href=f"/entities/{alert.entity_id}",
            severity=alert.severity,
            entity_id=alert.entity_id,
            entity_name=ent.name if ent else alert.entity_id,
        ))
    events.sort(key=lambda e: e.at, reverse=True)
    return events[:limit]
