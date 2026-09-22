from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.engine.cohort import _bucket_midpoint
from app.engine.inference.signals import extract
from app.omni.desk import build_creator_desk, build_web_desk
from app.schemas import CohortPayload, ReportPayload

_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    # select_autoescape() matches on the *file extension*, and every template here
    # ends in ".j2" — so the html/xml list silently resolved to False on all of them
    # and every report rendered scraped third-party text unescaped. A hostile creator
    # bio or YouTube comment became stored XSS executing same-origin on the shared
    # report link. Escape unconditionally; nothing in these templates emits raw HTML.
    autoescape=True,
    trim_blocks=True, lstrip_blocks=True,
)

AGE_MID = {"15-17": 16.0, "18-20": 19.0, "21-24": 22.5, "25-30": 27.5, "31+": 34.0}


def _d(dist, prefix: str = "", title: bool = False) -> dict:
    pct = dist.as_pct()
    keys = [f"{prefix}{k.replace('_', ' ').title() if title else k}" for k in pct]
    return {"k": keys, "v": list(pct.values())}


def chart_data_for(p: ReportPayload) -> dict:
    a = p.audience
    c = p.content
    f = p.funnel
    br = p.brand
    gr = p.growth
    cm = p.comments
    dx = p.diagnostics
    d = {
        "age": _d(a.age),
        "income": _d(a.income, prefix="₹"),
        "tier": _d(a.city_tier, title=True),
        "device": _d(a.device, title=True),
        "format": _d(a.format_mix, title=True),
        "season": {"k": list(a.seasonality.keys()), "v": list(a.seasonality.values())},
        "interests": {"k": [i["topic"] for i in a.interests],
                      "v": [i["share"] for i in a.interests]},
        "top": {"k": [], "v": []},
        "funnel": None,
        "occupation": _lab(a.occupation), "education": _lab(a.education_mix),
        "career": _lab(a.career_mix), "sophistication": _lab(a.sophistication),
        "consumption": _lab(a.consumption),
        "heat": _heatmap(a),
        "brand": None, "growth": None, "position": None,
        "sentiment": None, "intent": None, "matrix": None,
        "platforms": _platform_share(p), "competitors": _competitor_points(p),
        "evidence": None, "lorenz": None, "gaps": None, "prices": None,
    }
    if c and c.top_performers:
        d["top"] = {
            "k": [(x.title[:58] + "…") if len(x.title) > 58 else x.title
                  for x in c.top_performers],
            "v": [x.views for x in c.top_performers],
        }
    if f and f.scores:
        d["funnel"] = {"k": [s.dimension for s in f.scores],
                       "v": [s.value for s in f.scores]}
    if br:
        d["brand"] = {"k": [x.name for x in br.pillars], "v": [x.score for x in br.pillars]}
        d["position"] = {"name": p.subject_name, "x": br.position_x, "y": br.position_y}
    if gr and gr.trajectory:
        d["growth"] = {"k": [t["period"] for t in gr.trajectory],
                       "v": [t["median_views"] for t in gr.trajectory]}
    if cm and cm.available:
        d["sentiment"] = {"k": ["Positive", "Neutral", "Negative"],
                          "v": [cm.sentiment.get("positive", 0), cm.sentiment.get("neutral", 0),
                                cm.sentiment.get("negative", 0)]}
        if cm.buckets:
            d["intent"] = {"k": [b.label for b in cm.buckets],
                           "v": [b.share for b in cm.buckets]}
    if c and c.measured_items >= 4:
        pts = []
        for item in p.raw.all_content():
            if item.views and item.duration_seconds:
                pts.append({"x": round(item.duration_seconds / 60, 1), "y": item.views,
                            "t": item.title[:56]})
        d["matrix"] = pts[:200]
    if dx:
        d["evidence"] = {
            "k": ["Observed", "Calculated", "Modelled", "Unavailable"],
            "v": [dx.evidence_counts.get("observed", 0),
                  dx.evidence_counts.get("calculated", 0),
                  dx.evidence_counts.get("modelled", 0),
                  dx.evidence_counts.get("unavailable", 0)],
        }
        d["lorenz"] = dx.lorenz
        d["gaps"] = {"k": [x["label"] for x in dx.upload_gaps],
                     "v": [x["days"] for x in dx.upload_gaps]}
        if f and f.rungs:
            d["prices"] = {"k": [r.name for r in f.rungs if r.price_inr],
                           "v": [r.price_inr for r in f.rungs if r.price_inr]}
    return d


def _lab(dist):
    if not dist:
        return {"k": [], "v": []}
    from app.engine.inference import benchmarks as B
    pct = dist.as_pct()
    return {"k": [B.LABELS.get(k, k.replace("_", " ").title()) for k in pct],
            "v": list(pct.values())}


def _heatmap(a) -> dict:
    """Age × city-tier concentration, as a bubble grid."""
    ages = list(a.age.as_pct().keys())
    tiers = [k.replace("_", " ").title() for k in a.city_tier.as_pct()]
    apct, tpct = list(a.age.as_pct().values()), list(a.city_tier.as_pct().values())
    rows = []
    for ti, tv in enumerate(tpct):
        pts = []
        for ai, av in enumerate(apct):
            idx = (av * tv) / 100.0           # joint concentration index
            pts.append({"x": ai, "r": max(3, min(30, (idx * 3) ** 0.5 * 3))})
        rows.append({"tier": tiers[ti], "points": pts})
    return {"ages": ages, "tiers": tiers, "rows": rows}


def _platform_share(p: ReportPayload) -> dict:
    rows = [(f"{pl.platform.title()} @{pl.handle}" if pl.handle else pl.platform.title(),
             pl.followers or 0) for pl in p.platforms if pl.followers]
    rows.sort(key=lambda r: -r[1])
    return {"k": [r[0] for r in rows], "v": [r[1] for r in rows]}


def _competitor_points(p: ReportPayload) -> list:
    cs = p.competitors
    if not cs or not getattr(cs, "assessed", False):
        return []
    pts = []
    subj = cs.subject_followers or 0
    if subj:
        pts.append({"name": p.subject_name + " (subject)", "x": subj, "y": 100,
                    "r": 16, "self": True})
    for c in cs.competitors:
        if not c.followers:
            continue
        pts.append({"name": c.display_name or c.handle, "x": c.followers,
                    "y": c.content_overlap if c.content_overlap is not None else 20,
                    "r": 11, "self": False})
    return pts[:10]


def _platform_line(p: ReportPayload) -> str:
    seen: set[str] = set()
    parts = []
    for account in p.raw.accounts:
        if (not account.followers or account.raw.get("analysis_eligible") is False or
                account.raw.get("identity_role", "primary") != "primary"):
            continue
        key = f"{account.platform}:{(account.handle or account.url).lower()}"
        if key in seen:
            continue
        seen.add(key)
        parts.append(f"{account.platform} {account.followers:,}")
    return " · ".join(parts) or "no public follower counts available"


def render(payload: ReportPayload) -> str:
    if not payload.desk:
        raw = payload.raw
        payload.desk = build_creator_desk(
            name=payload.subject_name,
            handle=payload.subject_handle or "",
            overview=payload.overview, audience=payload.audience,
            signals=extract(raw) if raw else None,
            content=payload.content, media_buy=payload.media_buy,
            keyless=(raw.keyless if raw else None) or {},
            accounts=raw.accounts if raw else [],
        ).model_dump()
    return _env.get_template("report.html.j2").render(
        p=payload,
        platform_line=_platform_line(payload),
        chart_data={"": chart_data_for(payload)},
    )


def render_web(payload) -> str:
    """Website intelligence report (app.omni.webintel.WebIntelPayload)."""
    if not getattr(payload, "desk", None):
        payload.desk = build_web_desk(payload).model_dump()
    return _env.get_template("web_report.html.j2").render(w=payload)


def render_media(payload) -> str:
    """Post/video public-metadata report."""
    return _env.get_template("media_report.html.j2").render(m=payload)


def render_cohort(cp: CohortPayload) -> str:
    charts = {f"c{i + 1}": chart_data_for(p) for i, p in enumerate(cp.reports)}
    lifecycle = []
    if cp.cohort:
        for i, p in enumerate(cp.reports):
            pct = p.audience.age.as_pct()
            median_age = (sum(_bucket_midpoint(k) * v for k, v in pct.items()) / 100
                          if pct else 25.0)
            aud = sum(
                acc.followers or 0 for acc in p.raw.accounts
                if acc.raw.get("analysis_eligible") is not False
                and acc.raw.get("identity_role", "primary") == "primary"
            )
            lifecycle.append({
                "name": p.subject_name, "x": round(median_age, 1),
                "y": i + 1,
                "r": max(8, min(38, int((aud or 1) ** 0.28))),
            })
    return _env.get_template("cohort.html.j2").render(
        cp=cp, chart_data=charts, lifecycle_data=lifecycle)
