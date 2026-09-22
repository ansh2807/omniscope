"""Tenant graph of stored entities and evidenced links (spec §24).

Nodes and edges come from Entity and EntityLink rows only. A shared name
never creates an edge.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.models import Entity, EntityLink


class GraphNode(BaseModel):
    id: str
    name: str
    kind: str
    domain: str = ""
    score: float | None = None
    watched: bool = False
    href: str = ""


class GraphEdge(BaseModel):
    from_id: str
    to_id: str
    from_name: str = ""
    to_name: str = ""
    rel: str
    evidence: str = ""
    method: str = ""
    confidence: float = 0.0
    href: str = ""


class GraphMap(BaseModel):
    assessed: bool = False
    reason: str = ""
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    isolated_n: int = 0
    methodology: str = (
        "Edges are stored EntityLink rows (HAS_ACCOUNT, LINKS_TO, SAME_AS) "
        "created from hard identifiers. Names are never a merge key.")


def build(session: Session, org_id: str | None) -> GraphMap:
    query = select(Entity).order_by(Entity.updated_at.desc())
    if org_id is not None:
        query = query.where(Entity.org_id == org_id)
    else:
        query = query.where(Entity.org_id == None)  # noqa: E711
    entities = list(session.exec(query).all())[:200]
    if not entities:
        return GraphMap(assessed=False, reason="No stored entities yet.")
    by_id = {e.id: e for e in entities}
    ids = set(by_id)
    link_query = select(EntityLink)
    if org_id is not None:
        link_query = link_query.where(EntityLink.org_id == org_id)
    else:
        link_query = link_query.where(EntityLink.org_id == None)  # noqa: E711
    edges: list[GraphEdge] = []
    linked: set[str] = set()
    for link in session.exec(link_query).all():
        if link.from_id not in ids or link.to_id not in ids:
            continue
        left, right = by_id[link.from_id], by_id[link.to_id]
        edges.append(GraphEdge(
            from_id=left.id,
            to_id=right.id,
            from_name=left.name,
            to_name=right.name,
            rel=link.rel,
            evidence=link.evidence,
            method=link.method,
            confidence=link.confidence,
            href=f"/entities/{left.id}",
        ))
        linked.add(left.id)
        linked.add(right.id)
    nodes = [GraphNode(
        id=e.id, name=e.name, kind=e.kind, domain=e.domain or "",
        score=e.last_score, watched=bool(e.watched),
        href=f"/entities/{e.id}",
    ) for e in entities]
    return GraphMap(
        assessed=True,
        nodes=nodes,
        edges=edges,
        isolated_n=sum(1 for n in nodes if n.id not in linked),
    )
