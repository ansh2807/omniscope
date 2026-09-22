"""Media-buy decision scorecard for marketing companies.

Produces an auditable prioritize / pilot / hold / pass recommendation from public
evidence only. Competes with HypeAuditor/CreatorIQ diligence dashboards without
claiming private platform facts.
"""
from __future__ import annotations

from typing import Any


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _status(metric: Any) -> str:
    if metric is None:
        return "unavailable"
    if isinstance(metric, dict):
        return str(metric.get("status") or "unavailable")
    return str(getattr(metric, "status", "unavailable") or "unavailable")


def _value(metric: Any) -> Any:
    if metric is None:
        return None
    if isinstance(metric, dict):
        return metric.get("value")
    return getattr(metric, "value", None)


def build_media_buy_scorecard(
    *,
    agency: dict[str, Any] | None,
    signals: Any = None,
    content: Any = None,
    brand: Any = None,
    diagnostics: Any = None,
    audience: Any = None,
) -> dict[str, Any]:
    """Return a renderer-ready media-buy scorecard."""
    agency = agency or {}
    components: list[dict[str, Any]] = []
    weighted = 0.0
    weight_sum = 0.0

    def add(name: str, score: float | None, weight: float, note: str, status: str) -> None:
        nonlocal weighted, weight_sum
        if score is None:
            components.append({"name": name, "score": None, "weight": weight,
                               "status": status, "note": note})
            return
        score = max(0.0, min(100.0, float(score)))
        components.append({"name": name, "score": round(score, 1), "weight": weight,
                           "status": status, "note": note})
        weighted += score * weight
        weight_sum += weight

    # Scale / reachability
    total = float(_get(signals, "total_audience") or 0)
    if total >= 1_000_000:
        add("Public scale", 92, 18, f"{int(total):,} summed public follows", "calculated")
    elif total >= 100_000:
        add("Public scale", 78, 18, f"{int(total):,} summed public follows", "calculated")
    elif total >= 10_000:
        add("Public scale", 58, 18, f"{int(total):,} summed public follows", "calculated")
    elif total > 0:
        add("Public scale", 35, 18, f"{int(total):,} summed public follows", "calculated")
    else:
        add("Public scale", None, 18, "No public follower totals collected", "unavailable")

    # Delivery evidence
    sub_to_view = _get(content, "sub_to_view")
    current_median = _get(content, "current_median")
    measured = int(_get(content, "measured_items") or 0)
    if sub_to_view is not None and measured >= 4:
        pct = float(sub_to_view) * 100
        # Healthy public delivery often sits well below 100% of subs; score mid-range honestly.
        score = 85 if 1.5 <= pct <= 25 else 70 if 0.5 <= pct < 1.5 or 25 < pct <= 40 else 45 if pct < 0.5 else 55
        add("Recent delivery ratio", score, 20,
            f"Median recent views / subscribers = {pct:.2f}% across {measured} items",
            "calculated")
    elif current_median and measured >= 4:
        score = 72 if current_median >= 50_000 else 60 if current_median >= 10_000 else 48
        add("Recent delivery ratio", score, 20,
            f"Median recent public views {int(current_median):,} · {measured} items",
            "calculated")
    else:
        add("Recent delivery ratio", None, 20,
            "Need ≥4 items with public view counts", "unavailable")

    # Audience quality proxy
    aq = agency.get("audience_quality")
    if _status(aq) in ("modelled", "calculated"):
        val = _value(aq) or {}
        add("Audience-signal quality", float(val.get("score") or 50), 15,
            val.get("label") or "Public-signal quality proxy", _status(aq))
    else:
        add("Audience-signal quality", None, 15,
            "Insufficient public interaction/comment signals", "unavailable")

    # Anomaly risk (invert)
    ff = agency.get("fake_follower_anomaly")
    if _status(ff) == "modelled":
        val = _value(ff) or {}
        risk = float(val.get("central_risk_score") or 50)
        add("Anomaly risk (inverted)", max(0, 100 - risk), 15,
            f"{val.get('risk_band', 'screened')} · not a fake-follower %", "modelled")
    else:
        add("Anomaly risk (inverted)", None, 15,
            "Multi-signal anomaly screen not eligible", "unavailable")

    # Brand evidence
    brand_total = _get(brand, "total")
    if brand_total is not None:
        add("Brand evidence rubric", float(brand_total) * 2, 12,
            f"Internal public-evidence rubric {brand_total}/50", "calculated")
    else:
        add("Brand evidence rubric", None, 12, "Brand analysis unavailable", "unavailable")

    # Research completeness
    ev = _get(diagnostics, "evidence_score")
    if ev is not None:
        add("Research completeness", float(ev), 10,
            f"Evidence coverage index {ev}/100", "calculated")
    else:
        add("Research completeness", None, 10, "Diagnostics unavailable", "unavailable")

    # Contactability
    ct = agency.get("contact_details")
    if _status(ct) == "observed":
        n = len(_value(ct) or [])
        add("Contactability", min(100, 60 + n * 15), 10,
            f"{n} public contact route(s) on creator-owned surfaces", "observed")
    else:
        add("Contactability", 25, 10,
            "No public business email/contact route observed", "unavailable")

    coverage = round((weight_sum / 100) * 100) if weight_sum else 0
    fit = round(weighted / weight_sum, 1) if weight_sum >= 35 else None

    conf = _get(audience, "overall_confidence")
    conf_pct = round(float(conf) * 100) if conf is not None else None

    if fit is None:
        verdict = "insufficient_evidence"
        label = "Hold — collect more public evidence"
        color = "warn"
    elif fit >= 75 and (conf_pct is None or conf_pct >= 45):
        verdict = "prioritize"
        label = "Prioritize for pilot"
        color = "good"
    elif fit >= 58:
        verdict = "pilot"
        label = "Pilot with tracked pilot"
        color = "acc"
    elif fit >= 42:
        verdict = "hold"
        label = "Hold — resolve open diligence gaps"
        color = "warn"
    else:
        verdict = "pass"
        label = "Pass for now"
        color = "bad"

    reasons: list[str] = []
    risks: list[str] = []
    next_steps: list[str] = []

    for c in components:
        if c["score"] is None:
            risks.append(f"{c['name']}: {c['note']}")
        elif c["score"] >= 70:
            reasons.append(f"{c['name']} {c['score']}/100 — {c['note']}")
        elif c["score"] < 45:
            risks.append(f"{c['name']} {c['score']}/100 — {c['note']}")

    if _status(agency.get("estimated_reach")) == "modelled":
        band = (_value(agency.get("estimated_reach")) or {}).get("per_placement_range")
        if band and len(band) == 2:
            reasons.append(f"Public placement-view proxy {band[0]:,}–{band[1]:,}")
            next_steps.append("Contract on first-party impressions/reach, not the public-view proxy.")
    if _status(agency.get("contact_details")) != "observed":
        next_steps.append("Request media kit + business contact before commercial negotiation.")
    if _status(agency.get("fake_follower_anomaly")) != "modelled":
        next_steps.append("Request follower-growth + reach authenticity export for integrity checks.")
    next_steps.append("Run one tracked pilot with a single KPI before scale spend.")
    if not reasons:
        reasons.append("Public evidence is limited; treat this as discovery input only.")

    return {
        "verdict": verdict,
        "label": label,
        "color": color,
        "fit_score": fit,
        "coverage_pct": coverage,
        "confidence_note": (
            f"Life-stage model confidence {conf_pct}%" if conf_pct is not None else
            "Life-stage confidence not available"
        ),
        "components": components,
        "reasons": reasons[:5],
        "risks": risks[:5],
        "next_steps": next_steps[:5],
        "method": (
            "Weighted mean of available public diligence components. Missing components "
            "reduce coverage rather than silently scoring zero. Not a guaranteed campaign ROI."
        ),
    }
