"""Cohort layer — what a report gains when you paste more than one link.

Adds the analysis that only exists in relation to other creators: topic affinity,
evidence-bounded lifecycle hypotheses, a comparison matrix and an investment verdict.
Exact audience overlap remains unavailable without first-party exports.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from app.schemas import ReportPayload

AGE_MIDPOINT = {"15-17": 16.0, "18-20": 19.0, "21-24": 22.5, "25-30": 27.5, "31+": 34.0}


def _bucket_midpoint(label: str) -> float:
    if label in AGE_MIDPOINT:
        return AGE_MIDPOINT[label]
    nums = [int(n) for n in re.findall(r"\d+", label)]
    if len(nums) >= 2:
        return (nums[0] + nums[1]) / 2
    if nums:
        return float(nums[0] + (3 if "+" in label else 0))
    return 25.0


@dataclass
class Overlap:
    a: str
    b: str
    low: int | None
    high: int | None
    confidence: int
    mechanism: str
    topic_similarity: int = 0
    status: str = "unavailable"


@dataclass
class Verdict:
    name: str
    best_for: str
    efficiency: str
    scale_ceiling: str
    recommendation: str


@dataclass
class CohortAnalysis:
    subjects: list[str] = field(default_factory=list)
    headline: str = ""
    lede: str = ""
    findings: list[dict] = field(default_factory=list)
    matrix: list[dict] = field(default_factory=list)
    overlaps: list[Overlap] = field(default_factory=list)
    lifecycle: list[dict] = field(default_factory=list)
    verdicts: list[Verdict] = field(default_factory=list)
    total_audience: int = 0
    max_overlap: int | None = None
    median_overlap: int | None = None
    overlap_measurable: bool = False
    competing_pairs: int = 0
    sequential_pairs: int = 0
    seasonality_note: str = ""


def _median_age(payload: ReportPayload) -> float:
    pct = payload.audience.age.as_pct()
    return sum(_bucket_midpoint(k) * v for k, v in pct.items()) / 100.0 if pct else 25.0


def _age_overlap(a: ReportPayload, b: ReportPayload) -> float:
    pa, pb = a.audience.age.as_pct(), b.audience.age.as_pct()
    return sum(min(pa.get(k, 0), pb.get(k, 0)) for k in set(pa) | set(pb)) / 100.0


def _topic_overlap(a: ReportPayload, b: ReportPayload) -> float:
    ta = {i["key"]: i["share"] for i in a.audience.interests}
    tb = {i["key"]: i["share"] for i in b.audience.interests}
    if not ta or not tb:
        return 0.3
    keys = set(ta) | set(tb)
    dot = sum(ta.get(k, 0) * tb.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in ta.values()))
    nb = math.sqrt(sum(v * v for v in tb.values()))
    return dot / (na * nb) if na and nb else 0.0


def _geo_factor(a: ReportPayload, b: ReportPayload) -> tuple[float, str]:
    """Only penalise geography when at least one side is genuinely locked to a place.

    Modelled city lists for two national creators will differ by construction, and
    treating that as a real geographic divergence would understate every overlap.
    """
    ta = (a.audience.top_cities.confidence
          if a.audience.top_cities and a.audience.top_cities.status.value == "observed" else 0.0)
    tb = (b.audience.top_cities.confidence
          if b.audience.top_cities and b.audience.top_cities.status.value == "observed" else 0.0)
    ca = (a.audience.top_cities.value if a.audience.top_cities else []) or []
    cb = (b.audience.top_cities.value if b.audience.top_cities else []) or []
    sa, sb = set(map(str.lower, ca[:5])), set(map(str.lower, cb[:5]))
    locked = max(ta, tb) >= 0.65        # at least one geography was observed, not modelled
    if not sa or not sb or not locked:
        return 0.85, ""
    shared = sa & sb
    if not shared:
        return 0.30, (" One of the two is locked to a specific catchment the other does not "
                      "serve, which suppresses overlap further.")
    return 0.6 + 0.4 * (len(shared) / max(len(sa | sb), 1)), ""


def analyse(payloads: list[ReportPayload]) -> CohortAnalysis:
    ca = CohortAnalysis(subjects=[p.subject_name for p in payloads])
    ca.total_audience = sum(
        sum(a.followers or 0 for a in p.raw.accounts) for p in payloads)

    # ---------------------------------------------------------------- overlap
    for i, a in enumerate(payloads):
        for b in payloads[i + 1:]:
            age = _age_overlap(a, b)
            topic = _topic_overlap(a, b)
            geo, geo_note = _geo_factor(a, b)
            # Topic and modelled life stage support affinity hypotheses only. They are never
            # converted to a shared-follower percentage.
            gap = abs(_median_age(a) - _median_age(b))

            related = (topic > 0.20 or
                       {a.audience.archetype, b.audience.archetype} <= {
                           "exam_prep_educator", "admissions_desk", "entrance_mentor",
                           "career_finance_creator", "skill_educator"})
            if gap >= 3.0 and related:
                mech = (f"Possible lifecycle handoff: modelled median life stages are roughly "
                        f"{gap:.0f} years apart on related subject matter. This is a campaign "
                        f"hypothesis, not evidence that the same followers move between them."
                        + geo_note)
            elif gap >= 6:
                mech = (f"A {gap:.0f}-year gap in modelled life stage suggests lower affinity, "
                        f"but follower overlap remains unmeasured."
                        + geo_note)
            elif topic > 0.55:
                mech = ("Same subject matter and a similar modelled life stage suggest possible "
                        "competition. Unique-follower overlap is not public." + geo_note)
            else:
                mech = ("Adjacent content/life-stage hypothesis; actual shared followers are "
                        "not measurable from public metadata."
                        + geo_note)

            ca.overlaps.append(Overlap(a.subject_name, b.subject_name, None, None, 0, mech,
                                       topic_similarity=round(topic * 100)))
    ca.competing_pairs = sum(1 for o in ca.overlaps if "competition" in o.mechanism)
    ca.sequential_pairs = sum(1 for o in ca.overlaps if "handoff" in o.mechanism)

    # -------------------------------------------------------------- lifecycle
    ordered = sorted(payloads, key=_median_age)
    for p in ordered:
        pct = p.audience.age.as_pct()
        modal = max(pct, key=pct.get)
        ca.lifecycle.append({
            "name": p.subject_name,
            "handle": p.subject_handle,
            "median_age": round(_median_age(p), 1),
            "modal_band": modal,
            "archetype": p.audience.archetype_label,
            "one_liner": p.audience.one_liner,
        })

    # ----------------------------------------------------------------- matrix
    for p in payloads:
        a = p.audience
        aud = sum(acc.followers or 0 for acc in p.raw.accounts)
        pct = a.age.as_pct()
        gpct = a.gender.as_pct()
        peak = max(a.seasonality, key=a.seasonality.get) if a.seasonality else "—"
        prices = [r.price_inr for r in (p.funnel.rungs if p.funnel else []) if r.price_inr]
        ca.matrix.append({
            "name": p.subject_name,
            "one_liner": a.one_liner.split("—")[0].strip(),
            "audience": f"{aud:,}",
            "modal_age": max(pct, key=pct.get),
            "gender": (f"{gpct.get('male', 0)} / {gpct.get('female', 0)}"
                       if gpct else "Unavailable"),
            "income_modal": f"₹{a.income.modal}" if a.income.modal else "Unavailable",
            "language": (a.language.value.split(",")[0]
                         if a.language and a.language.confidence > 0 else "Unavailable"),
            "primary_platform": max(
                ((acc.platform, acc.followers or 0) for acc in p.raw.accounts),
                key=lambda t: t[1], default=("—", 0))[0],
            "price_ceiling": f"₹{int(max(prices)):,}" if prices else "none found",
            "peak_month": peak,
            "confidence": f"{round(a.overall_confidence * 100)}%",
        })

    # --------------------------------------------------------------- verdicts
    for p in payloads:
        ca.verdicts.append(_verdict(p))

    # --------------------------------------------------------------- findings
    ca.findings = _findings(payloads, ca)

    # ------------------------------------------------------------- narrative
    if ca.lifecycle:
        first, last = ca.lifecycle[0], ca.lifecycle[-1]
        span = f"{first['modal_band'].split('-')[0]} to {last['modal_band'].replace('+','')}"
        ca.headline = "Follower overlap is unavailable; the report provides affinity hypotheses only."
        ca.lede = (
            f"Public creator metadata cannot reveal shared follower IDs or unique cross-platform "
            f"reach. Modelled life stages span {first['median_age']} to {last['median_age']} "
            f"(roughly {span}), producing {ca.sequential_pairs} possible lifecycle handoffs and "
            f"{ca.competing_pairs} possible competitive pairs. Validate both with creator "
            f"Insights before deduplicating reach or allocating budget.")

    peaks = {}
    for p in payloads:
        if p.audience.seasonality:
            peaks[p.subject_name] = max(p.audience.seasonality,
                                        key=p.audience.seasonality.get)
    if len(set(peaks.values())) >= max(2, len(peaks) - 1) and peaks:
        ca.seasonality_note = (
            "Measured content-sample peak months differ — "
            + ", ".join(f"{n} peaks in {m}" for n, m in peaks.items())
            + ". This may justify a scheduling test, but it does not establish audience demand "
              "or campaign reach.")
    return ca


def _verdict(p: ReportPayload) -> Verdict:
    aud = sum(acc.followers or 0 for acc in p.raw.accounts)
    proof = (p.funnel.social_proof.get("ratings") if p.funnel else None) or 0
    best = (f"Unvalidated awareness/partnership test; {aud:,} summed public account follows "
            "are visible, with duplicates and unique reach unknown")
    if proof:
        best += f". {proof} public ratings add social proof but do not establish purchases"
    return Verdict(
        name=p.subject_name,
        best_for=best,
        efficiency="Unavailable until a trackable pilot",
        scale_ceiling="Unavailable without unique reach and delivery-capacity data",
        recommendation=("Request first-party audience/reach evidence, define one conversion "
                        "event, and run a bounded pilot before selecting commercial terms."),
    )


def _findings(payloads: list[ReportPayload], ca: CohortAnalysis) -> list[dict]:
    """Promote the most material per-creator callouts to cohort level, then add the
    findings that only exist across the set."""
    scored: list[tuple[float, dict]] = []
    weight = {"risk": 3.0, "correction": 2.6, "opportunity": 2.2, "insight": 1.6}
    for p in payloads:
        aud = sum(a.followers or 0 for a in p.raw.accounts) or 1
        scale = min(2.0, math.log10(aud) / 5)
        for c in p.audience.callouts:
            scored.append((weight.get(c["kind"], 1.0) * (1 + scale),
                           {"kind": c["kind"],
                            "title": f"{p.subject_name}: {c['title']}",
                            "body": c["body"]}))
    scored.sort(key=lambda t: -t[0])
    out = [d for _, d in scored[:6]]

    if len(payloads) > 1:
        out.insert(0, {
            "kind": "risk",
            "title": "Unique follower overlap was not measured",
            "body": (
                "Topic and modelled life-stage proximity can suggest testable affinity, but "
                "cannot produce an overlap percentage. Request creator Insights or run a "
                "deduplicated reach study before summing audiences or assuming competition. "
                + ca.seasonality_note),
        })
        sequential = [o for o in ca.overlaps if "handoff" in o.mechanism.lower()]
        if sequential:
            best = max(sequential, key=lambda o: o.topic_similarity)
            out.insert(1, {
                "kind": "opportunity",
                "title": f"{best.a} and {best.b} are a handoff, not a duplicate",
                "body": (
                    f"{best.mechanism} Treat the handoff as an experiment; neither shared "
                    "followers nor monetisation of the transition were measured."),
            })
    return out[:8]
