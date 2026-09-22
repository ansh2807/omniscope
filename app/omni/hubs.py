"""Read stored report payloads into intelligence-hub tables.

Hubs never invent rows. If nobody has Deep Analyzed a website, the hub is empty.
"""
from __future__ import annotations

import json

from sqlmodel import Session, select

from app.models import Alert, Entity, Report, SourceDocument
from app.omni.coverage import from_payload


def _org_match(query, model, org_id: str | None):
    if org_id is not None:
        return query.where(model.org_id == org_id)
    return query.where(model.org_id == None)  # noqa: E711


def latest_web_payloads(session: Session, org_id: str | None,
                        *, limit: int = 40) -> list[tuple[Report, dict]]:
    query = _org_match(select(Report).where(Report.kind == "web"), Report, org_id)
    query = query.order_by(Report.created_at.desc())
    out: list[tuple[Report, dict]] = []
    for report in session.exec(query).all()[:limit]:
        if not report.payload_json:
            continue
        try:
            data = json.loads(report.payload_json)
        except ValueError:
            continue
        if isinstance(data, dict):
            out.append((report, data))
    return out


def overview_stats(session: Session, org_id: str | None) -> dict:
    entities = list(session.exec(
        _org_match(select(Entity), Entity, org_id)).all())
    alerts = list(session.exec(
        _org_match(select(Alert), Alert, org_id)).all())
    docs = list(session.exec(
        _org_match(select(SourceDocument), SourceDocument, org_id)).all())
    webs = latest_web_payloads(session, org_id, limit=8)
    return {
        "entities": len(entities),
        "watched": sum(1 for e in entities if e.watched),
        "alerts": len(alerts),
        "documents": len(docs),
        "web_reports": len(webs),
        "recent": webs,
    }


def competitor_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        intel = data.get("competitor_intel") or {}
        for rival in intel.get("competitors") or []:
            rows.append({
                "subject": data.get("entity_name") or report.subject_name,
                "href": f"/r/{report.share_slug}",
                "name": rival.get("name") or rival.get("domain"),
                "domain": rival.get("domain") or "",
                "snippet": (rival.get("snippet") or "")[:160],
            })
    return rows[:80]


def product_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        intel = data.get("product_intel") or {}
        for offer in intel.get("ladder") or data.get("products") or []:
            rows.append({
                "subject": data.get("entity_name") or report.subject_name,
                "href": f"/r/{report.share_slug}",
                "name": offer.get("name") or "—",
                "price": offer.get("price_inr"),
                "rating": offer.get("rating"),
            })
    return rows[:80]


def market_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        intel = data.get("market_intel") or {}
        for part in intel.get("participants") or []:
            rows.append({
                "subject": data.get("entity_name") or report.subject_name,
                "href": f"/r/{report.share_slug}",
                "name": part.get("name") or part.get("domain"),
                "domain": part.get("domain") or "",
                "query": intel.get("query_used") or "",
            })
    return rows[:80]


def seo_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        sm = data.get("seo_map") or {}
        missing = [s["slot"] for s in sm.get("slots") or [] if s.get("status") == "missing"]
        thin = [s["slot"] for s in sm.get("slots") or [] if s.get("status") == "thin"]
        rows.append({
            "subject": data.get("entity_name") or report.subject_name,
            "href": f"/r/{report.share_slug}",
            "domain": data.get("domain") or "",
            "missing": ", ".join(missing) or "—",
            "thin": ", ".join(thin) or "—",
        })
    return rows


def trend_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        tr = data.get("trend_intel") or {}
        rows.append({
            "subject": data.get("entity_name") or report.subject_name,
            "href": f"/r/{report.share_slug}",
            "class": tr.get("classification") or "insufficient",
            "velocity": tr.get("velocity"),
            "score": data.get("overall_score"),
        })
    return rows


def brand_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        socials = data.get("socials") or []
        live = [s.get("platform") for s in socials
                if isinstance(s, dict) and not s.get("error")]
        rows.append({
            "subject": data.get("entity_name") or report.subject_name,
            "href": f"/r/{report.share_slug}",
            "tagline": (data.get("tagline") or "")[:120],
            "score": data.get("overall_score"),
            "socials": ", ".join(live) or "—",
        })
    return rows


def content_rows(session: Session, org_id: str | None, *, limit: int = 40) -> list[dict]:
    query = _org_match(select(Report).where(Report.kind == "single"), Report, org_id)
    query = query.order_by(Report.created_at.desc())
    rows = []
    for report in session.exec(query).all()[:limit]:
        if not report.payload_json:
            continue
        try:
            data = json.loads(report.payload_json)
        except ValueError:
            continue
        content = data.get("content") or {}
        if not isinstance(content, dict):
            continue
        patterns = content.get("winning_patterns") or []
        hooks = ", ".join(
            (p.get("phrase") if isinstance(p, dict) else str(p))[:40]
            for p in patterns[:3]) or "—"
        rows.append({
            "subject": report.subject_name,
            "href": f"/r/{report.share_slug}",
            "items": content.get("measured_items") or content.get("total_items") or "—",
            "hooks": hooks,
            "format": content.get("format_verdict") or "—",
        })
    return rows


def risk_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        rk = data.get("risk_intel") or {}
        if not rk.get("assessed"):
            continue
        if rk.get("level") == "none" and not rk.get("crisis_n"):
            continue
        rows.append({
            "subject": data.get("entity_name") or report.subject_name,
            "href": f"/r/{report.share_slug}",
            "level": rk.get("level") or "none",
            "crisis": rk.get("crisis_n") or 0,
            "criticism": rk.get("criticism_n") or 0,
        })
    return rows


def related_documents(session: Session, entity, org_id: str | None) -> list:
    needles = [n.lower() for n in (entity.domain, entity.name) if n and len(n) >= 3]
    if not needles:
        return []
    docs = list(session.exec(
        _org_match(select(SourceDocument), SourceDocument, org_id)).all())
    hits = []
    for doc in docs:
        blob = f"{doc.filename} {doc.excerpt} {doc.intel_json or ''}".lower()
        if any(n in blob for n in needles):
            hits.append(doc)
    return hits[:12]


def tech_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        subject = data.get("entity_name") or report.subject_name
        for tech in data.get("tech") or []:
            if not isinstance(tech, dict) or not tech.get("name"):
                continue
            rows.append({
                "subject": subject,
                "href": f"/r/{report.share_slug}",
                "name": tech.get("name") or "",
                "category": tech.get("category") or "",
                "evidence": (tech.get("evidence") or "")[:160],
            })
    return rows[:80]


def site_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    """Flatten robots / well-known / headers / schema already on reports."""
    rows = []
    for report, data in payloads:
        subject = data.get("entity_name") or report.subject_name
        href = f"/r/{report.share_slug}"
        robots = data.get("robots_intel") or {}
        if robots.get("assessed"):
            for path in robots.get("disallow") or []:
                rows.append({"subject": subject, "href": href, "kind": "robots",
                             "item": "disallow", "value": path})
            if robots.get("crawl_delay"):
                rows.append({"subject": subject, "href": href, "kind": "robots",
                             "item": "crawl-delay", "value": robots["crawl_delay"]})
        for f in (data.get("public_intel") or {}).get("files") or []:
            if not isinstance(f, dict):
                continue
            rows.append({
                "subject": subject, "href": href, "kind": "file",
                "item": f.get("path") or "",
                "value": "present" if f.get("present") else f"absent ({f.get('status') or 0})",
            })
        present = (data.get("header_intel") or {}).get("present") or {}
        if isinstance(present, dict):
            for name, val in present.items():
                rows.append({"subject": subject, "href": href, "kind": "header",
                             "item": name, "value": str(val)[:120]})
        header = data.get("header_intel") or {}
        for item, key in (("last-modified", "last_modified"), ("etag", "etag"),
                          ("date", "date"), ("cache-control", "cache_control"),
                          ("x-robots-tag", "x_robots_tag")):
            value = header.get(key) or ""
            if value:
                rows.append({"subject": subject, "href": href, "kind": "freshness",
                             "item": item, "value": str(value)[:120]})
        for host in (data.get("vendor_intel") or {}).get("unique") or []:
            if host:
                rows.append({"subject": subject, "href": href, "kind": "vendor",
                             "item": "host", "value": str(host)[:120]})
        for host in (data.get("header_intel") or {}).get("csp_hosts") or []:
            if host:
                rows.append({"subject": subject, "href": href, "kind": "csp",
                             "item": "host", "value": str(host)[:120]})
        for item in (data.get("link_intel") or {}).get("rows") or []:
            if isinstance(item, dict) and item.get("rel") and item.get("url"):
                rows.append({
                    "subject": subject, "href": href, "kind": "link",
                    "item": item["rel"],
                    "value": item["url"][:160],
                })
        for item in (data.get("ads_intel") or {}).get("rows") or []:
            if not isinstance(item, dict) or not item.get("exchange"):
                continue
            rows.append({
                "subject": subject, "href": href, "kind": "ads",
                "item": item.get("path") or "/ads.txt",
                "value": f"{item.get('exchange')} · {item.get('relationship')} · "
                         f"{item.get('publisher')}"[:160],
            })
        for item in (data.get("index_intel") or {}).get("pages") or []:
            if not isinstance(item, dict):
                continue
            if not item.get("raw") and not item.get("tokens"):
                continue
            rows.append({
                "subject": subject, "href": href, "kind": "robots-meta",
                "item": item.get("source") or "meta",
                "value": (item.get("raw") or ", ".join(item.get("tokens") or []))[:160],
            })
        for item in (data.get("schema_intel") or {}).get("items") or []:
            if not isinstance(item, dict):
                continue
            rows.append({
                "subject": subject, "href": href, "kind": "schema",
                "item": item.get("type") or "",
                "value": ((item.get("name") or "") + (
                    f" · {item['extra']}" if item.get("extra") else ""))[:160],
            })
    return rows[:120]


def structured_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    """FAQ, jobs, events, articles, breadcrumbs, NAP, visible ₹ and linked surfaces."""
    rows = []
    for report, data in payloads:
        intel = data.get("schema_intel") or {}
        subject = data.get("entity_name") or report.subject_name
        href = f"/r/{report.share_slug}"
        for item in intel.get("faqs") or []:
            if isinstance(item, dict) and item.get("question"):
                rows.append({"subject": subject, "href": href, "kind": "faq",
                             "title": item["question"],
                             "detail": (item.get("answer") or "")[:160]})
        for item in intel.get("jobs") or []:
            if isinstance(item, dict) and item.get("title"):
                loc = item.get("location") or item.get("employment") or ""
                detail = " · ".join(
                    x for x in (loc, item.get("salary"), item.get("valid_through"))
                    if x)
                rows.append({"subject": subject, "href": href, "kind": "job",
                             "title": item["title"], "detail": detail[:160]})
        for item in intel.get("events") or []:
            if isinstance(item, dict) and item.get("name"):
                detail = " · ".join(
                    x for x in (item.get("start"), item.get("location"),
                                item.get("offer")) if x)
                rows.append({"subject": subject, "href": href, "kind": "event",
                             "title": item["name"], "detail": detail[:160]})
        nap = intel.get("nap") or {}
        if isinstance(nap, dict) and any(
                nap.get(k) for k in ("telephone", "address", "email", "hours", "geo")):
            rows.append({"subject": subject, "href": href, "kind": "nap",
                         "title": nap.get("name") or subject,
                         "detail": " · ".join(
                             x for x in (nap.get("telephone"), nap.get("address"),
                                         nap.get("hours"), nap.get("geo")) if x)[:160]})
        for item in intel.get("hreflang") or []:
            if isinstance(item, dict) and item.get("lang"):
                rows.append({"subject": subject, "href": href, "kind": "hreflang",
                             "title": item["lang"], "detail": (item.get("url") or "")[:160]})
        for item in intel.get("articles") or []:
            if isinstance(item, dict) and item.get("title"):
                detail = " · ".join(
                    x for x in (
                        (f"published {item['published']}" if item.get("published") else ""),
                        (f"modified {item['modified']}" if item.get("modified") else ""),
                        (item.get("url") or ""),
                    ) if x)
                rows.append({"subject": subject, "href": href, "kind": "article",
                             "title": item["title"],
                             "detail": detail[:160]})
        for item in intel.get("courses") or []:
            if isinstance(item, dict) and item.get("name"):
                detail = " · ".join(
                    x for x in (item.get("kind"), item.get("provider"),
                                item.get("code"), item.get("start"),
                                item.get("credential")) if x)
                rows.append({"subject": subject, "href": href, "kind": "course",
                             "title": item["name"], "detail": detail[:160]})
        for item in intel.get("contact_points") or []:
            if not isinstance(item, dict):
                continue
            if not (item.get("telephone") or item.get("email") or item.get("contact_type")):
                continue
            rows.append({
                "subject": subject, "href": href, "kind": "contact_point",
                "title": item.get("contact_type") or item.get("telephone") or item.get("email"),
                "detail": " · ".join(
                    x for x in (item.get("telephone"), item.get("email"),
                                item.get("area"), item.get("languages")) if x)[:160],
            })
        for item in intel.get("item_lists") or []:
            if isinstance(item, dict) and (item.get("name") or item.get("entries")):
                entries = item.get("entries") or []
                detail = ", ".join(entries[:6])
                if item.get("number_of_items"):
                    detail = f"{item['number_of_items']} printed · {detail}".strip(" ·")
                rows.append({"subject": subject, "href": href, "kind": "item_list",
                             "title": item.get("name") or "ItemList",
                             "detail": detail[:160]})
        for item in intel.get("aggregate_offers") or []:
            if not isinstance(item, dict):
                continue
            if not (item.get("low") or item.get("high") or item.get("offer_count")):
                continue
            span = "-".join(x for x in (item.get("low"), item.get("high")) if x)
            rows.append({
                "subject": subject, "href": href, "kind": "aggregate_offer",
                "title": item.get("name") or "AggregateOffer",
                "detail": " · ".join(
                    x for x in (span, item.get("currency"),
                                (f"{item['offer_count']} printed offer(s)"
                                 if item.get("offer_count") else "")) if x)[:160],
            })
        for item in intel.get("offer_catalogs") or []:
            if isinstance(item, dict) and (item.get("name") or item.get("items")):
                rows.append({
                    "subject": subject, "href": href, "kind": "offer_catalog",
                    "title": item.get("name") or "OfferCatalog",
                    "detail": ", ".join((item.get("items") or [])[:6])[:160],
                })
        for item in intel.get("speakable") or []:
            if not isinstance(item, dict):
                continue
            selectors = item.get("selectors") or []
            if not (item.get("name") or selectors):
                continue
            rows.append({
                "subject": subject, "href": href, "kind": "speakable",
                "title": item.get("name") or (selectors[0] if selectors else "speakable"),
                "detail": ", ".join(selectors[:6])[:160],
            })
        for item in intel.get("hours") or []:
            if not isinstance(item, dict):
                continue
            if not (item.get("day") or item.get("opens") or item.get("closes")):
                continue
            span = "-".join(x for x in (item.get("opens"), item.get("closes")) if x)
            rows.append({
                "subject": subject, "href": href, "kind": "hours",
                "title": item.get("day") or item.get("name") or "hours",
                "detail": " · ".join(
                    x for x in (item.get("name"), span,
                                item.get("valid_through")) if x)[:160],
            })
        for item in intel.get("web_pages") or []:
            if not isinstance(item, dict):
                continue
            if not (item.get("last_reviewed") or item.get("reviewed_by")
                    or item.get("specialty") or item.get("significant_links")):
                continue
            links = item.get("significant_links") or []
            rows.append({
                "subject": subject, "href": href, "kind": "webpage",
                "title": item.get("name") or item.get("kind") or "WebPage",
                "detail": " · ".join(
                    x for x in (
                        (f"lastReviewed {item['last_reviewed']}"
                         if item.get("last_reviewed") else ""),
                        item.get("reviewed_by"),
                        item.get("specialty"),
                        ", ".join(links[:4]),
                    ) if x)[:160],
            })
        for item in intel.get("breadcrumbs") or []:
            if isinstance(item, dict) and item.get("path"):
                rows.append({"subject": subject, "href": href, "kind": "breadcrumb",
                             "title": item["path"],
                             "detail": (item.get("url") or "")[:160]})
        for item in (data.get("product_intel") or {}).get("visible_prices") or []:
            if not isinstance(item, dict) or item.get("amount") is None:
                continue
            rows.append({"subject": subject, "href": href, "kind": "price",
                         "title": f"₹{item['amount']:,.0f}",
                         "detail": (item.get("excerpt") or item.get("url") or "")[:160]})
        for item in (data.get("surface_intel") or {}).get("links") or []:
            if isinstance(item, dict) and item.get("url"):
                rows.append({"subject": subject, "href": href, "kind": "surface",
                             "title": item.get("kind") or "link",
                             "detail": item["url"][:160]})
        for item in intel.get("people") or []:
            if isinstance(item, dict) and item.get("name"):
                rows.append({"subject": subject, "href": href, "kind": "person",
                             "title": item["name"],
                             "detail": (item.get("job_title") or "")[:160]})
        for item in intel.get("videos") or []:
            if isinstance(item, dict) and item.get("title"):
                rows.append({"subject": subject, "href": href, "kind": "video",
                             "title": item["title"],
                             "detail": (item.get("uploaded") or item.get("url") or "")[:160]})
        for item in intel.get("howtos") or []:
            if isinstance(item, dict) and item.get("name"):
                steps = item.get("steps") or 0
                tools = item.get("tools") or []
                detail = f"{steps} printed step(s)"
                if tools:
                    detail += " · tools " + ", ".join(tools[:6])
                if item.get("total_time"):
                    detail += f" · {item['total_time']}"
                rows.append({"subject": subject, "href": href, "kind": "howto",
                             "title": item["name"],
                             "detail": detail[:160]})
        for item in intel.get("search_actions") or []:
            if isinstance(item, dict) and item.get("target"):
                rows.append({"subject": subject, "href": href, "kind": "search",
                             "title": "SearchAction",
                             "detail": item["target"][:160]})
        serving = intel.get("serving") or {}
        if isinstance(serving, dict) and any(
                serving.get(k) for k in ("area", "payments", "price_range",
                                         "languages", "employees", "also_known")):
            also = serving.get("also_known") or []
            alias = ", ".join(also) if isinstance(also, list) else str(also)
            rows.append({"subject": subject, "href": href, "kind": "serving",
                         "title": serving.get("area") or serving.get("payments") or "serving",
                         "detail": " · ".join(
                             x for x in (serving.get("payments"),
                                         serving.get("price_range"),
                                         serving.get("languages"),
                                         (f"employees printed {serving['employees']}"
                                          if serving.get("employees") else ""),
                                         alias) if x)[:160]})
        for item in intel.get("apps") or []:
            if isinstance(item, dict) and item.get("name"):
                rows.append({"subject": subject, "href": href, "kind": "app",
                             "title": item["name"],
                             "detail": " · ".join(
                                 x for x in (item.get("kind"), item.get("os"),
                                             item.get("url")) if x)[:160]})
        for item in (data.get("product_intel") or {}).get("policies") or []:
            if not isinstance(item, dict) or not item.get("detail"):
                continue
            rows.append({"subject": subject, "href": href,
                         "kind": item.get("kind") or "policy",
                         "title": item.get("name") or item.get("kind") or "offer",
                         "detail": (item.get("detail") or "")[:160]})
        for item in (data.get("product_intel") or {}).get("catalog") or []:
            if not isinstance(item, dict) or not item.get("value"):
                continue
            rows.append({"subject": subject, "href": href,
                         "kind": item.get("kind") or "catalog",
                         "title": item.get("name") or item.get("kind") or "offer",
                         "detail": str(item["value"])[:160]})
        cards = data.get("card_intel") or {}
        if cards.get("twitter_site"):
            rows.append({"subject": subject, "href": href, "kind": "twitter",
                         "title": cards["twitter_site"],
                         "detail": (cards.get("twitter_card") or "twitter:site")[:160]})
        if cards.get("og_type"):
            rows.append({"subject": subject, "href": href, "kind": "og",
                         "title": cards["og_type"],
                         "detail": (cards.get("og_title") or "")[:160]})
        for item in cards.get("banners") or []:
            if isinstance(item, dict) and item.get("value"):
                rows.append({"subject": subject, "href": href, "kind": "app_banner",
                             "title": item.get("kind") or "app",
                             "detail": str(item["value"])[:160]})
    return rows[:140]


def legal_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        intel = data.get("legal_intel") or {}
        if not intel.get("assessed"):
            continue
        subject = data.get("entity_name") or report.subject_name
        for item in intel.get("policies") or []:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            rows.append({
                "subject": subject,
                "href": f"/r/{report.share_slug}",
                "kind": item.get("kind") or "",
                "updated": item.get("updated") or "",
                "title": item.get("title") or "",
                "url": item["url"],
            })
    return rows[:80]


def identity_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        intel = data.get("identity_intel") or {}
        claims = data.get("claims_intel") or {}
        if not intel.get("assessed") and not claims.get("assessed"):
            continue
        subject = data.get("entity_name") or report.subject_name
        href = f"/r/{report.share_slug}"
        for item in intel.get("ids") or []:
            if not isinstance(item, dict) or not item.get("value"):
                continue
            rows.append({
                "subject": subject,
                "href": href,
                "kind": item.get("kind") or "",
                "value": item["value"],
                "source": item.get("source") or "",
            })
        for kind in claims.get("verifications") or []:
            if kind:
                rows.append({
                    "subject": subject, "href": href,
                    "kind": "verify", "value": kind, "source": "meta",
                })
        for item in claims.get("rel_me") or []:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            rows.append({
                "subject": subject, "href": href,
                "kind": "rel_me", "value": item["url"], "source": "link",
            })
        for item in claims.get("same_as") or []:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            rows.append({
                "subject": subject, "href": href,
                "kind": "same_as", "value": item["url"],
                "source": item.get("via") or "schema",
            })
    return rows[:80]


def wellknown_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    """Trust / AI / people / ads / privacy inventory from stored public files."""
    rows = []
    for report, data in payloads:
        subject = data.get("entity_name") or report.subject_name
        href = f"/r/{report.share_slug}"
        intel = data.get("public_intel") or {}
        inventory = intel.get("inventory") or []
        if inventory:
            for item in inventory:
                if not isinstance(item, dict):
                    continue
                rows.append({
                    "subject": subject, "href": href,
                    "role": item.get("role") or "",
                    "path": item.get("path") or "",
                    "present": item.get("present") or "",
                    "note": item.get("note") or "",
                })
            continue
        for item in intel.get("files") or []:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            path = item["path"]
            role = item.get("role") or ""
            if "security.txt" in path:
                role = role or "trust"
            elif path in {"/llms.txt", "/ai.txt"}:
                role = role or "ai"
            elif path.endswith("humans.txt"):
                role = role or "people"
            if not role:
                continue
            rows.append({
                "subject": subject, "href": href,
                "role": role, "path": path,
                "present": "yes" if item.get("present") else "no",
                "note": "",
            })
    return rows[:120]


def filings_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    """SEC / GLEIF / MCA rows already stored. No guessed valuation."""
    rows = []
    for report, data in payloads:
        intel = data.get("filings_intel") or {}
        if not intel.get("assessed") and not intel.get("identifiers"):
            continue
        subject = data.get("entity_name") or report.subject_name
        href = f"/r/{report.share_slug}"
        for rec in intel.get("records") or []:
            if not isinstance(rec, dict) or not rec.get("identifier"):
                continue
            latest = ""
            for filing in rec.get("filings") or []:
                if isinstance(filing, dict) and filing.get("form"):
                    latest = f"{filing.get('form')} {filing.get('filed') or ''}".strip()
                    break
            rows.append({
                "subject": subject, "href": href,
                "kind": rec.get("kind") or "",
                "identifier": rec["identifier"],
                "name": rec.get("name") or "",
                "status": rec.get("status") or "",
                "latest": latest or (rec.get("reason") or rec.get("detail") or "")[:160],
            })
    return rows[:80]


def onpage_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        intel = data.get("onpage_intel") or {}
        if not intel.get("assessed"):
            continue
        subject = data.get("entity_name") or report.subject_name
        for item in intel.get("hits") or []:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            rows.append({
                "subject": subject,
                "href": f"/r/{report.share_slug}",
                "kind": item.get("kind") or "",
                "provider": item.get("provider") or "",
                "url": item["url"],
            })
    return rows[:80]


def surface_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    """App store, GitHub and status URLs already linked from stored pages."""
    rows = []
    for report, data in payloads:
        intel = data.get("surface_intel") or {}
        if not intel.get("assessed"):
            continue
        subject = data.get("entity_name") or report.subject_name
        for item in intel.get("links") or []:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            rows.append({
                "subject": subject,
                "href": f"/r/{report.share_slug}",
                "kind": item.get("kind") or "",
                "host": item.get("host") or "",
                "url": item["url"],
            })
    return rows[:80]


def locale_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    """Printed html lang / og:locale / hreflang / Content-Language tags."""
    rows = []
    for report, data in payloads:
        intel = data.get("locale_intel") or {}
        if not intel.get("assessed"):
            continue
        subject = data.get("entity_name") or report.subject_name
        href = f"/r/{report.share_slug}"
        for lang in intel.get("langs") or []:
            if lang:
                rows.append({"subject": subject, "href": href,
                             "kind": "html_lang", "value": lang})
        for loc in intel.get("og_locales") or []:
            if loc:
                rows.append({"subject": subject, "href": href,
                             "kind": "og_locale", "value": loc})
        for loc in intel.get("hreflang") or []:
            if loc:
                rows.append({"subject": subject, "href": href,
                             "kind": "hreflang", "value": loc})
        header = intel.get("content_language") or ""
        if header:
            rows.append({"subject": subject, "href": href,
                         "kind": "content_language", "value": header})
    return rows[:80]


def feed_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        intel = data.get("feed_intel") or {}
        if not intel.get("assessed"):
            continue
        subject = data.get("entity_name") or report.subject_name
        for item in intel.get("items") or []:
            if not isinstance(item, dict):
                continue
            if not item.get("title") and not item.get("url"):
                continue
            rows.append({
                "subject": subject,
                "href": f"/r/{report.share_slug}",
                "title": item.get("title") or item.get("url") or "—",
                "published": item.get("published") or "",
                "url": item.get("url") or "",
                "source": item.get("source_feed") or "",
            })
    return rows[:80]


def news_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        intel = data.get("news_intel") or {}
        if not intel.get("assessed"):
            continue
        subject = data.get("entity_name") or report.subject_name
        for item in intel.get("items") or []:
            rows.append({
                "subject": subject,
                "href": f"/r/{report.share_slug}",
                "title": item.get("title") or item.get("url") or "—",
                "narrative": item.get("narrative") or "other",
                "source": item.get("source_host") or "",
                "published": item.get("published") or "",
                "status": item.get("page_status") or "search",
                "url": item.get("url") or "",
            })
    return rows[:80]


def desk_rows(session: Session, org_id: str | None, *, limit: int = 40) -> list[dict]:
    """Stored DESK briefs from website and creator reports. Never invented."""
    query = _org_match(
        select(Report).where(Report.kind.in_(["web", "single"])), Report, org_id)
    query = query.order_by(Report.created_at.desc())
    rows = []
    for report in session.exec(query).all()[:limit]:
        if not report.payload_json:
            continue
        try:
            data = json.loads(report.payload_json)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        desk = data.get("desk") or {}
        if not isinstance(desk, dict) or not desk.get("job"):
            continue
        needs = [n for n in (desk.get("needs") or []) if isinstance(n, dict)]
        una = sum(1 for n in needs if n.get("status") == "unavailable")
        rows.append({
            "subject": data.get("entity_name") or report.subject_name,
            "href": f"/r/{report.share_slug}",
            "kind": desk.get("kind") or report.kind,
            "job": (desk.get("job") or "")[:200],
            "posture": (desk.get("posture") or "")[:160],
            "unavailable": una,
            "needs": len(needs),
        })
    return rows[:80]


def opportunity_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        subject = data.get("entity_name") or report.subject_name
        for opp in data.get("opportunities") or []:
            if not isinstance(opp, dict) or not opp.get("title"):
                continue
            rows.append({
                "subject": subject,
                "href": f"/r/{report.share_slug}",
                "title": opp.get("title") or "",
                "why": (opp.get("why") or "")[:200],
                "evidence": (opp.get("evidence") or "")[:160],
            })
    return rows[:80]


def social_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        subject = data.get("entity_name") or report.subject_name
        for soc in data.get("socials") or []:
            if not isinstance(soc, dict) or not soc.get("platform"):
                continue
            followers = soc.get("followers")
            rows.append({
                "subject": subject,
                "href": f"/r/{report.share_slug}",
                "platform": soc.get("platform") or "",
                "handle": soc.get("handle") or "",
                "followers": followers if followers is not None else "—",
                "status": soc.get("error") or "observed",
                "url": soc.get("url") or "",
            })
    return rows[:80]


def contact_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        subject = data.get("entity_name") or report.subject_name
        contacts = data.get("contacts") or {}
        for email in contacts.get("emails") or []:
            if email:
                rows.append({
                    "subject": subject,
                    "href": f"/r/{report.share_slug}",
                    "kind": "email",
                    "value": str(email),
                })
        for phone in contacts.get("phones") or []:
            if phone:
                rows.append({
                    "subject": subject,
                    "href": f"/r/{report.share_slug}",
                    "kind": "phone",
                    "value": str(phone),
                })
    return rows[:80]


def unavailable_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    """Declared unmeasured items already on stored reports. Not a TAM gap list."""
    rows = []
    for report, data in payloads:
        subject = data.get("entity_name") or report.subject_name
        for item in data.get("unavailable") or []:
            if not isinstance(item, dict) or not item.get("item"):
                continue
            rows.append({
                "subject": subject,
                "href": f"/r/{report.share_slug}",
                "item": item.get("item") or "",
                "why": (item.get("why") or "")[:220],
            })
    return rows[:100]


def coverage_rows(payloads: list[tuple[Report, dict]]) -> list:
    rows = []
    for report, data in payloads:
        rows.append(from_payload(
            data,
            subject=data.get("entity_name") or report.subject_name,
            href=f"/r/{report.share_slug}",
        ))
    return rows


def review_rows(payloads: list[tuple[Report, dict]]) -> list[dict]:
    rows = []
    for report, data in payloads:
        ri = data.get("review_intel") or {}
        if not ri.get("assessed"):
            continue
        subject = data.get("entity_name") or report.subject_name
        href = f"/r/{report.share_slug}"
        theme_s = ", ".join(
            f"{k} {v}" for k, v in (ri.get("themes") or {}).items()) or "—"
        cards = [c for c in (ri.get("ratings") or []) if isinstance(c, dict)
                 and (c.get("value") or c.get("count"))]
        if cards:
            for card in cards:
                rows.append({
                    "subject": subject,
                    "href": href,
                    "rating": card.get("value") or ri.get("aggregate_rating"),
                    "count": card.get("count") or ri.get("aggregate_count"),
                    "themes": card.get("via") or theme_s,
                })
            continue
        rows.append({
            "subject": subject,
            "href": href,
            "rating": ri.get("aggregate_rating"),
            "count": ri.get("item_count") or ri.get("aggregate_count"),
            "themes": theme_s,
        })
    return rows
