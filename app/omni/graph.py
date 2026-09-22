"""Intelligence graph — entities, evidence, snapshots, aliases and links."""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlmodel import Session, select

from app.models import (Alert, Entity, EntityAlias, EntityLink, EntitySnapshot,
                        EvidenceItem)
from app.omni.evidence import EvidenceLog
from app.omni.events import ENTITY_DISCOVERED, ENTITY_RESOLVED, emit
from app.omni.oracle import HistoryPoint, detect_changes
from app.omni.resolve import (KIND_HANDLE, KIND_NAME, CreatorSurface, Identifier,
                              identifiers_from_creator, identifiers_from_input,
                              identifiers_from_web, is_entity_domain,
                              normalize_handle)
from app.omni.webintel import SocialPresence, WebIntelPayload


def find_entity(session: Session, domain: str, org_id: str | None) -> Entity | None:
    domain = (domain or "").lower()
    rows = list(session.exec(
        select(Entity).where(Entity.kind == "website", Entity.domain == domain)).all())
    return next((r for r in rows if r.org_id == org_id), None)


def load_history(session: Session, domain: str, org_id: str | None,
                 *, limit: int = 12) -> list[HistoryPoint]:
    entity = find_entity(session, domain, org_id)
    if entity is None:
        return []
    rows = list(session.exec(
        select(EntitySnapshot).where(EntitySnapshot.entity_id == entity.id)
        .order_by(EntitySnapshot.created_at.asc())).all())
    out: list[HistoryPoint] = []
    for row in rows[-limit:]:
        try:
            tech = json.loads(row.tech_json or "[]")
            socials = json.loads(row.socials_json or "[]")
        except ValueError:
            tech, socials = [], []
        out.append(HistoryPoint(
            overall_score=row.overall_score,
            tech=tech if isinstance(tech, list) else [],
            socials=socials if isinstance(socials, list) else [],
            latest_dated_content=row.latest_dated_content,
            observed_at=row.created_at.isoformat(),
        ))
    return out


def upsert_from_web(session: Session, payload: WebIntelPayload, *,
                    org_id: str | None, report_id: str) -> Entity:
    """Create or refresh the entity, append a snapshot, emit watch alerts."""
    domain = (payload.domain or "").lower()
    entity = find_entity(session, domain, org_id)
    previous_score = entity.last_score if entity else None
    prev_snap = entity.snapshot() if entity else {}
    prev_tech = list(prev_snap.get("tech") or [])
    prev_socials = list(prev_snap.get("socials") or [])
    watched = bool(entity.watched) if entity else False

    tech = [t.name for t in payload.tech][:12]
    socials = [s.platform for s in payload.socials if not s.error][:8]
    latest_dated = None
    if isinstance(payload.content, dict):
        latest_dated = payload.content.get("latest_dated_content")
    snapshot = {
        "overall_score": payload.overall_score,
        "tagline": payload.tagline,
        "tech": tech,
        "socials": socials,
    }
    now = datetime.utcnow()
    if entity is None:
        entity = Entity(
            id=uuid.uuid4().hex[:12],
            org_id=org_id,
            kind="website",
            name=payload.entity_name,
            domain=domain,
            canonical_url=payload.seed_url,
            last_report_id=report_id,
            last_score=payload.overall_score,
            snapshot_json=json.dumps(snapshot),
            watched=True,
            created_at=now,
            updated_at=now,
        )
    else:
        entity.name = payload.entity_name or entity.name
        entity.canonical_url = payload.seed_url or entity.canonical_url
        entity.last_report_id = report_id
        entity.last_score = payload.overall_score
        entity.snapshot_json = json.dumps(snapshot)
        entity.updated_at = now
    session.add(entity)
    session.flush()

    session.add(EntitySnapshot(
        id=uuid.uuid4().hex[:12],
        entity_id=entity.id,
        report_id=report_id,
        overall_score=payload.overall_score,
        tech_json=json.dumps(tech),
        socials_json=json.dumps(socials),
        latest_dated_content=str(latest_dated) if latest_dated else None,
        created_at=now,
    ))
    extras = list(session.exec(
        select(EntitySnapshot).where(EntitySnapshot.entity_id == entity.id)
        .order_by(EntitySnapshot.created_at.desc())).all())
    for stale in extras[24:]:
        session.delete(stale)
    _replace_evidence(session, entity.id, report_id, org_id, payload.evidence)

    if watched:
        drafts = detect_changes(
            watched=True, previous_score=previous_score,
            current_score=payload.overall_score,
            tech_added=sorted(set(tech) - set(prev_tech)),
            tech_removed=sorted(set(prev_tech) - set(tech)),
            socials_added=sorted(set(socials) - set(prev_socials)),
            socials_removed=sorted(set(prev_socials) - set(socials)),
        )
        for draft in drafts:
            session.add(Alert(
                id=uuid.uuid4().hex[:12],
                org_id=org_id,
                entity_id=entity.id,
                kind=draft["kind"],
                severity=draft["severity"],
                title=draft["title"],
                detail=draft["detail"],
            ))

    # Handles live on the social surface, not on the website row — otherwise
    # find_by_handle would collapse the company into the account.
    web_idents = [i for i in identifiers_from_web(payload) if i.kind != KIND_HANDLE]
    _put_aliases(session, entity, org_id, web_idents)
    for social in payload.socials:
        child = _upsert_social_surface(session, social, org_id=org_id,
                                       report_id=report_id)
        if child is None:
            continue
        _link(session, org_id, entity.id, child.id, "HAS_ACCOUNT",
              evidence=social.url or f"{social.platform}:{social.handle}",
              method="website_link" if not social.error else "website_claim",
              confidence=0.9 if not social.error else 0.7)
        _link(session, org_id, child.id, entity.id, "LINKS_TO",
              evidence=payload.domain,
              method="website_link" if not social.error else "website_claim",
              confidence=0.9 if not social.error else 0.7)
    reconcile(session, entity, org_id)

    session.commit()
    session.refresh(entity)
    return entity


def upsert_from_creator(session: Session, surface: CreatorSurface, *,
                        org_id: str | None, report_id: str) -> Entity:
    """Create or refresh a creator surface and link any owned-website domain."""
    handle = normalize_handle(surface.handle)
    platform = (surface.platform or "").lower()
    entity = find_by_handle(session, platform, handle, org_id) if handle else None
    now = datetime.utcnow()
    snapshot = {
        "platform": platform,
        "handle": handle,
        "websites": [d for d, _ in surface.website_domains],
    }
    if entity is None:
        entity = Entity(
            id=uuid.uuid4().hex[:12],
            org_id=org_id,
            kind="creator",
            name=surface.name or (f"@{handle}" if handle else surface.seed_url),
            domain=surface.website_domains[0][0] if surface.website_domains else "",
            canonical_url=surface.seed_url,
            last_report_id=report_id,
            last_score=surface.score,
            snapshot_json=json.dumps(snapshot),
            watched=False,
            created_at=now,
            updated_at=now,
        )
        emit(ENTITY_DISCOVERED, kind="creator", handle=handle, platform=platform)
    else:
        entity.name = surface.name or entity.name
        entity.canonical_url = surface.seed_url or entity.canonical_url
        entity.last_report_id = report_id
        entity.last_score = surface.score
        if surface.website_domains and not entity.domain:
            entity.domain = surface.website_domains[0][0]
        entity.snapshot_json = json.dumps(snapshot)
        entity.updated_at = now
    session.add(entity)
    session.flush()
    _put_aliases(session, entity, org_id, identifiers_from_creator(surface))
    for domain, url in surface.website_domains:
        if not is_entity_domain(domain):
            continue
        site = find_entity(session, domain, org_id)
        if site is None:
            continue
        _link(session, org_id, entity.id, site.id, "LINKS_TO",
              evidence=url, method="owned_link", confidence=0.85)
        _link(session, org_id, site.id, entity.id, "HAS_ACCOUNT",
              evidence=url, method="owned_link", confidence=0.85)
    reconcile(session, entity, org_id)
    session.commit()
    session.refresh(entity)
    return entity


def reconcile(session: Session, entity: Entity, org_id: str | None) -> int:
    """Link this entity to others that share a hard identifier in the same tenant."""
    aliases = list(session.exec(
        select(EntityAlias).where(EntityAlias.entity_id == entity.id)).all())
    linked = 0
    for alias in aliases:
        if alias.kind == KIND_NAME:
            continue
        for other in find_by_alias(session, org_id, alias.kind, alias.value,
                                   alias.platform):
            if other.id == entity.id:
                continue
            rel, reverse = _rel_pair(entity.kind, other.kind)
            _link(session, org_id, entity.id, other.id, rel,
                  evidence=f"{alias.kind}:{alias.value}",
                  method=alias.method or "alias_overlap",
                  confidence=alias.confidence or 0.8)
            _link(session, org_id, other.id, entity.id, reverse,
                  evidence=f"{alias.kind}:{alias.value}",
                  method=alias.method or "alias_overlap",
                  confidence=alias.confidence or 0.8)
            linked += 1
    if linked:
        emit(ENTITY_RESOLVED, entity_id=entity.id, links=linked)
    return linked


def find_by_handle(session: Session, platform: str, handle: str,
                   org_id: str | None) -> Entity | None:
    handle = normalize_handle(handle)
    platform = (platform or "").lower()
    if not handle or not platform:
        return None
    rows = [e for e in find_by_alias(session, org_id, KIND_HANDLE, handle, platform)
            if e.kind == "creator"]
    return rows[0] if rows else None


def find_by_alias(session: Session, org_id: str | None, kind: str, value: str,
                  platform: str = "") -> list[Entity]:
    query = select(EntityAlias).where(
        EntityAlias.kind == kind, EntityAlias.value == value)
    if platform:
        query = query.where(EntityAlias.platform == platform)
    out: list[Entity] = []
    seen: set[str] = set()
    for alias in session.exec(query).all():
        entity = session.get(Entity, alias.entity_id)
        if entity is None or entity.id in seen:
            continue
        if entity.org_id != org_id:
            continue
        seen.add(entity.id)
        out.append(entity)
    return out


def lookup(session: Session, *, org_id: str | None, kind: str, value: str,
           platform: str = "", handle: str = "", domain: str = "") -> dict:
    """Resolve an input against stored aliases. Name-only is never 'resolved'."""
    idents = identifiers_from_input(kind, value, platform=platform,
                                    handle=handle, domain=domain)
    matches: list[dict] = []
    seen: set[str] = set()
    for ident in idents:
        if ident.kind == KIND_NAME:
            continue
        for entity in find_by_alias(session, org_id, ident.kind, ident.value,
                                    ident.platform):
            if entity.id in seen:
                continue
            seen.add(entity.id)
            matches.append({
                "entity_id": entity.id,
                "name": entity.name,
                "kind": entity.kind,
                "domain": entity.domain,
                "url": entity.canonical_url,
                "confidence": ident.confidence,
                "reason": f"exact {ident.kind}"
                          + (f" {ident.platform}" if ident.platform else "")
                          + f" {ident.value}",
                "evidence": ident.source_url or ident.value,
            })
    if kind == "website" and domain:
        site = find_entity(session, domain, org_id)
        if site and site.id not in seen:
            matches.append({
                "entity_id": site.id, "name": site.name, "kind": site.kind,
                "domain": site.domain, "url": site.canonical_url,
                "confidence": 1.0, "reason": f"exact domain {domain}",
                "evidence": domain,
            })
    name_idents = [i for i in idents if i.kind == KIND_NAME]
    candidates: list[dict] = []
    if not matches and name_idents:
        for ident in name_idents:
            for entity in find_by_alias(session, org_id, KIND_NAME, ident.value):
                candidates.append({
                    "entity_id": entity.id, "name": entity.name, "kind": entity.kind,
                    "domain": entity.domain, "confidence": 0.35,
                    "reason": "shared display name — insufficient to resolve",
                    "evidence": ident.value,
                })
    if matches:
        verdict = "resolved" if any(m["confidence"] >= 0.85 for m in matches) \
            else "candidates"
        return {"verdict": verdict, "matches": matches, "candidates": [],
                "reason": ""}
    return {
        "verdict": "insufficient_evidence",
        "matches": [],
        "candidates": candidates,
        "reason": ("A shared name is not identity. Paste a domain or profile, "
                   "or run Deep Analyze so hard identifiers can be stored.")
        if candidates else
        "No stored entity matches this input. Deep Analyze it first.",
    }


def links_for(session: Session, entity_id: str) -> list[tuple[EntityLink, Entity]]:
    rows = list(session.exec(
        select(EntityLink).where(EntityLink.from_id == entity_id)
        .order_by(EntityLink.created_at.desc())).all())
    out: list[tuple[EntityLink, Entity]] = []
    for row in rows:
        other = session.get(Entity, row.to_id)
        if other is not None:
            out.append((row, other))
    return out


def aliases_for(session: Session, entity_id: str) -> list[EntityAlias]:
    return list(session.exec(
        select(EntityAlias).where(EntityAlias.entity_id == entity_id)).all())


def _put_aliases(session: Session, entity: Entity, org_id: str | None,
                 identifiers: list[Identifier]) -> None:
    existing = {(a.kind, a.value, a.platform) for a in session.exec(
        select(EntityAlias).where(EntityAlias.entity_id == entity.id)).all()}
    for ident in identifiers:
        key = (ident.kind, ident.value, ident.platform)
        if not ident.value or key in existing:
            continue
        session.add(EntityAlias(
            id=uuid.uuid4().hex[:12],
            entity_id=entity.id,
            org_id=org_id,
            kind=ident.kind,
            value=ident.value,
            platform=ident.platform,
            source_url=(ident.source_url or "")[:500],
            method=(ident.method or "")[:40],
            confidence=ident.confidence,
        ))
        existing.add(key)


def _upsert_social_surface(session: Session, social: SocialPresence, *,
                           org_id: str | None, report_id: str) -> Entity | None:
    from app.omni.resolve import social_from_url

    handle = normalize_handle(social.handle)
    platform = (social.platform or "").lower()
    if (not handle or not platform) and social.url:
        parsed = social_from_url(social.url)
        if parsed is not None:
            handle, platform = parsed.value, parsed.platform
    if not handle or not platform or platform == "website":
        return None
    entity = find_by_handle(session, platform, handle, org_id)
    now = datetime.utcnow()
    name = social.display_name or f"@{handle}"
    url = social.url or ""
    snapshot = {
        "platform": platform,
        "handle": handle,
        "followers": social.followers,
        "collected": not bool(social.error),
        "error": social.error or "",
    }
    if entity is None:
        entity = Entity(
            id=uuid.uuid4().hex[:12],
            org_id=org_id,
            kind="creator",
            name=name,
            domain="",
            canonical_url=url,
            last_report_id=report_id,
            last_score=None,
            snapshot_json=json.dumps(snapshot),
            watched=False,
            created_at=now,
            updated_at=now,
        )
        emit(ENTITY_DISCOVERED, kind="creator", handle=handle, platform=platform,
             via="website")
    else:
        if social.display_name:
            entity.name = social.display_name
        if url:
            entity.canonical_url = url
        snap = entity.snapshot()
        snap.update(snapshot)
        entity.snapshot_json = json.dumps(snap)
        entity.updated_at = now
    session.add(entity)
    session.flush()
    _put_aliases(session, entity, org_id, [Identifier(
        KIND_HANDLE, handle, platform=platform, source_url=url,
        method="website_link" if not social.error else "website_claim",
        confidence=0.9 if not social.error else 0.7,
    )])
    return entity


def _link(session: Session, org_id: str | None, from_id: str, to_id: str,
          rel: str, *, evidence: str, method: str, confidence: float) -> None:
    if from_id == to_id:
        return
    existing = session.exec(select(EntityLink).where(
        EntityLink.from_id == from_id, EntityLink.to_id == to_id,
        EntityLink.rel == rel)).first()
    if existing:
        if confidence > existing.confidence:
            existing.confidence = confidence
            existing.evidence = evidence[:400]
            existing.method = method[:40]
            session.add(existing)
        return
    session.add(EntityLink(
        id=uuid.uuid4().hex[:12],
        org_id=org_id,
        from_id=from_id,
        to_id=to_id,
        rel=rel,
        evidence=evidence[:400],
        method=method[:40],
        confidence=confidence,
    ))


def _rel_pair(kind_a: str, kind_b: str) -> tuple[str, str]:
    if kind_a == "website" and kind_b == "creator":
        return "HAS_ACCOUNT", "LINKS_TO"
    if kind_a == "creator" and kind_b == "website":
        return "LINKS_TO", "HAS_ACCOUNT"
    return "SAME_AS", "SAME_AS"


def _replace_evidence(session: Session, entity_id: str, report_id: str,
                      org_id: str | None, log: EvidenceLog) -> None:
    """Keep evidence for the latest run only — older hashes stay on past reports."""
    old = list(session.exec(select(EvidenceItem).where(
        EvidenceItem.entity_id == entity_id)).all())
    for row in old:
        session.delete(row)
    for rec in log.records[:40]:
        session.add(EvidenceItem(
            id=uuid.uuid4().hex[:12],
            entity_id=entity_id,
            report_id=report_id,
            org_id=org_id,
            claim=rec.claim[:300],
            source_url=rec.source_url[:500],
            method=rec.method[:40],
            collected_at=rec.collected_at[:40],
            content_sha256=(rec.content_sha256 or "")[:64] or None,
        ))
