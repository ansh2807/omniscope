"""Period digest of stored change (spec §31, §33).

Assembles alerts, snapshot score moves, and crisis/criticism news already on
reports. It does not forecast, and a quiet watch list is reported as no stored
change — not as 'healthy'.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.models import Alert, Entity, EntitySnapshot, Report
from app.omni.site import parse_http_date

SCORE_MOVE = 3.0  # same noise floor as ORACLE


class DigestItem(BaseModel):
    at: str
    entity_id: str = ""
    entity_name: str = ""
    kind: str                # alert | score | news
    title: str
    detail: str = ""
    severity: str = ""
    href: str = ""


class DigestIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    since: str = ""
    until: str = ""
    days: int = 7
    alert_n: int = 0
    score_n: int = 0
    news_n: int = 0
    watched_n: int = 0
    silent_watched: list[str] = Field(default_factory=list)
    items: list[DigestItem] = Field(default_factory=list)
    methodology: str = (
        "This digest restates stored alerts, snapshot score moves of 3+ points, "
        "crisis/criticism news, dated first-party feed items, dated schema "
        "articles, sampled policy dates, printed priceValidUntil values, and "
        "homepage Last-Modified dates, JobPosting validThrough, Event "
        "startDate, Course startDate, Article dateModified, WebPage "
        "lastReviewed and Review datePublished already on website reports. "
        "A header date is not a verified edit. dateModified and lastReviewed "
        "are not verified edits. A review date is not a verified review event. "
        "validThrough is not a hiring deadline or an open-now verdict. Quiet "
        "watched entities mean no stored change, not a health certificate.")


def _payload(report: Report | None) -> dict:
    if not report or not report.payload_json:
        return {}
    try:
        data = json.loads(report.payload_json)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def build(session: Session, org_id: str | None, *, days: int = 7) -> DigestIntel:
    days = min(max(int(days), 1), 30)
    until = datetime.utcnow()
    since = until - timedelta(days=days)
    entity_query = select(Entity)
    alert_query = select(Alert).where(Alert.created_at >= since)
    if org_id is not None:
        entity_query = entity_query.where(Entity.org_id == org_id)
        alert_query = alert_query.where(Alert.org_id == org_id)
    else:
        entity_query = entity_query.where(Entity.org_id == None)  # noqa: E711
        alert_query = alert_query.where(Alert.org_id == None)  # noqa: E711
    entities = {e.id: e for e in session.exec(entity_query).all()}
    items: list[DigestItem] = []
    touched: set[str] = set()

    for alert in session.exec(alert_query.order_by(Alert.created_at.desc())).all()[:80]:
        ent = entities.get(alert.entity_id)
        items.append(DigestItem(
            at=alert.created_at.isoformat(),
            entity_id=alert.entity_id,
            entity_name=ent.name if ent else alert.entity_id,
            kind="alert",
            title=alert.title,
            detail=alert.detail,
            severity=alert.severity,
            href=f"/entities/{alert.entity_id}",
        ))
        touched.add(alert.entity_id)

    for entity in entities.values():
        snaps = list(session.exec(
            select(EntitySnapshot).where(EntitySnapshot.entity_id == entity.id)
            .order_by(EntitySnapshot.created_at.desc())).all())[:2]
        if len(snaps) < 2 or snaps[0].created_at < since:
            continue
        delta = round(snaps[0].overall_score - snaps[1].overall_score, 1)
        if abs(delta) < SCORE_MOVE:
            continue
        items.append(DigestItem(
            at=snaps[0].created_at.isoformat(),
            entity_id=entity.id,
            entity_name=entity.name,
            kind="score",
            title=f"Score {delta:+.1f}",
            detail=f"{snaps[1].overall_score} → {snaps[0].overall_score} vs prior snapshot.",
            severity="watch" if abs(delta) >= 8 else "info",
            href=f"/entities/{entity.id}",
        ))
        touched.add(entity.id)

    report_query = select(Report).where(Report.kind == "web", Report.created_at >= since)
    if org_id is not None:
        report_query = report_query.where(Report.org_id == org_id)
    else:
        report_query = report_query.where(Report.org_id == None)  # noqa: E711
    for report in session.exec(report_query.order_by(Report.created_at.desc())).all()[:40]:
        news = (_payload(report).get("news_intel") or {})
        for row in news.get("items") or []:
            if not isinstance(row, dict):
                continue
            if row.get("narrative") not in {"crisis", "criticism"}:
                continue
            items.append(DigestItem(
                at=report.created_at.isoformat(),
                entity_id="",
                entity_name=report.subject_name,
                kind="news",
                title=row.get("title") or row.get("narrative") or "news",
                detail=row.get("narrative") or "",
                severity="watch" if row.get("narrative") == "crisis" else "info",
                href=row.get("url") or f"/r/{report.share_slug}",
            ))
        since_day = since.date().isoformat()
        until_day = until.date().isoformat()
        for row in (_payload(report).get("feed_intel") or {}).get("items") or []:
            if not isinstance(row, dict):
                continue
            published = (row.get("published") or "")[:10]
            if not published or published < since_day:
                continue
            items.append(DigestItem(
                at=published,
                entity_id="",
                entity_name=report.subject_name,
                kind="feed",
                title=row.get("title") or row.get("url") or "feed",
                detail="first-party feed",
                href=row.get("url") or f"/r/{report.share_slug}",
            ))
        for row in (_payload(report).get("schema_intel") or {}).get("articles") or []:
            if not isinstance(row, dict):
                continue
            published = (row.get("published") or "")[:10]
            modified = (row.get("modified") or "")[:10]
            if published and published >= since_day:
                items.append(DigestItem(
                    at=published,
                    entity_id="",
                    entity_name=report.subject_name,
                    kind="article",
                    title=row.get("title") or row.get("url") or "article",
                    detail="schema Article/BlogPosting datePublished",
                    href=row.get("url") or f"/r/{report.share_slug}",
                ))
            if modified and modified >= since_day and modified != published:
                items.append(DigestItem(
                    at=modified,
                    entity_id="",
                    entity_name=report.subject_name,
                    kind="article",
                    title=row.get("title") or row.get("url") or "article",
                    detail="printed dateModified (not a verified edit)",
                    href=row.get("url") or f"/r/{report.share_slug}",
                ))
        for row in (_payload(report).get("schema_intel") or {}).get("courses") or []:
            if not isinstance(row, dict):
                continue
            start = (row.get("start") or "")[:10]
            if not start or start < since_day or start > until_day:
                continue
            items.append(DigestItem(
                at=start,
                entity_id="",
                entity_name=report.subject_name,
                kind="course",
                title=row.get("name") or "course",
                detail="printed Course startDate (not enrollment)",
                href=row.get("url") or f"/r/{report.share_slug}",
            ))
        for row in (_payload(report).get("review_intel") or {}).get("items") or []:
            if not isinstance(row, dict):
                continue
            published = (row.get("published") or "")[:10]
            if not published or published < since_day:
                continue
            items.append(DigestItem(
                at=published,
                entity_id="",
                entity_name=report.subject_name,
                kind="review",
                title=(row.get("author") or row.get("body") or "review")[:80],
                detail="printed Review datePublished (not a verified review event)",
                href=row.get("source_url") or f"/r/{report.share_slug}",
            ))
        for row in (_payload(report).get("schema_intel") or {}).get("web_pages") or []:
            if not isinstance(row, dict):
                continue
            reviewed = (row.get("last_reviewed") or "")[:10]
            if not reviewed or reviewed < since_day:
                continue
            items.append(DigestItem(
                at=reviewed,
                entity_id="",
                entity_name=report.subject_name,
                kind="webpage",
                title=row.get("name") or row.get("kind") or "webpage",
                detail="printed lastReviewed (not a verified edit)",
                href=row.get("url") or f"/r/{report.share_slug}",
            ))
        for row in (_payload(report).get("legal_intel") or {}).get("policies") or []:
            if not isinstance(row, dict):
                continue
            updated = (row.get("updated") or "")[:10]
            if not updated or updated < since_day:
                continue
            items.append(DigestItem(
                at=updated,
                entity_id="",
                entity_name=report.subject_name,
                kind="legal",
                title=row.get("title") or row.get("kind") or "policy",
                detail="sampled policy page date",
                href=row.get("url") or f"/r/{report.share_slug}",
            ))
        for row in (_payload(report).get("product_intel") or {}).get("ladder") or []:
            if not isinstance(row, dict):
                continue
            valid = (row.get("valid_until") or "")[:10]
            if not valid or valid < since_day or valid > until_day:
                continue
            items.append(DigestItem(
                at=valid,
                entity_id="",
                entity_name=report.subject_name,
                kind="offer",
                title=row.get("name") or "offer",
                detail="printed priceValidUntil (not an expiry verdict)",
                href=row.get("url") or f"/r/{report.share_slug}",
            ))
        for row in (_payload(report).get("schema_intel") or {}).get("hours") or []:
            if not isinstance(row, dict):
                continue
            valid_through = (row.get("valid_through") or "")[:10]
            if not valid_through or valid_through < since_day or valid_through > until_day:
                continue
            items.append(DigestItem(
                at=valid_through,
                entity_id="",
                entity_name=report.subject_name,
                kind="hours",
                title=row.get("day") or row.get("name") or "hours",
                detail="printed OpeningHoursSpecification validThrough (not open-now)",
                href=row.get("url") or f"/r/{report.share_slug}",
            ))
        for row in (_payload(report).get("schema_intel") or {}).get("jobs") or []:
            if not isinstance(row, dict):
                continue
            valid_through = (row.get("valid_through") or "")[:10]
            if not valid_through or valid_through < since_day or valid_through > until_day:
                continue
            items.append(DigestItem(
                at=valid_through,
                entity_id="",
                entity_name=report.subject_name,
                kind="job",
                title=row.get("title") or "job",
                detail="printed JobPosting validThrough (not a hiring deadline)",
                href=row.get("url") or f"/r/{report.share_slug}",
            ))
        for row in (_payload(report).get("schema_intel") or {}).get("events") or []:
            if not isinstance(row, dict):
                continue
            start = (row.get("start") or "")[:10]
            if not start or start < since_day or start > until_day:
                continue
            items.append(DigestItem(
                at=start,
                entity_id="",
                entity_name=report.subject_name,
                kind="event",
                title=row.get("name") or "event",
                detail="printed Event startDate",
                href=row.get("url") or f"/r/{report.share_slug}",
            ))
        header = _payload(report).get("header_intel") or {}
        stamped = parse_http_date(str(header.get("last_modified") or ""))
        if stamped and since_day <= stamped <= until_day:
            items.append(DigestItem(
                at=stamped,
                entity_id="",
                entity_name=report.subject_name,
                kind="freshness",
                title="Homepage Last-Modified",
                detail="HTTP Last-Modified header (not a verified edit)",
                href=f"/r/{report.share_slug}",
            ))

    items.sort(key=lambda i: i.at, reverse=True)
    items = items[:60]
    watched = [e for e in entities.values() if e.watched]
    silent = sorted(e.name for e in watched if e.id not in touched)
    alert_n = sum(1 for i in items if i.kind == "alert")
    score_n = sum(1 for i in items if i.kind == "score")
    news_n = sum(1 for i in items if i.kind == "news")
    if not items and not silent:
        return DigestIntel(
            assessed=False,
            reason="No stored alerts, score moves, or crisis/criticism news in this window.",
            since=since.isoformat(timespec="minutes"),
            until=until.isoformat(timespec="minutes"),
            days=days,
            watched_n=len(watched),
        )
    reason = ""
    if not items and silent:
        reason = "Watched entities had no stored change in this window."
    return DigestIntel(
        assessed=True,
        reason=reason,
        since=since.isoformat(timespec="minutes"),
        until=until.isoformat(timespec="minutes"),
        days=days,
        alert_n=alert_n,
        score_n=score_n,
        news_n=news_n,
        watched_n=len(watched),
        silent_watched=silent[:40],
        items=items,
    )
