"""Evidence-qualified agency intelligence metrics.

This module is deliberately standalone: callers can pass the existing ``RawProfile``,
``Signals``, ``AudienceModel``, ``ContentAnalysis``, ``CompetitorSet``, comment and brand
objects, or dictionaries with the same fields.  No collector or renderer dependency is
required.

The public web cannot reveal private platform facts such as unique audience overlap,
audience demographics, actual fake-follower share, or campaign impressions.  Every
output therefore carries one of four claim statuses:

``observed``
    Reproduces a value exposed by an attributable source.
``calculated``
    Arithmetic over observed inputs; the formula and denominator are included.
``modelled``
    A transparent decision proxy.  It must not be presented as a platform fact.
``unavailable``
    The evidence cannot support the requested claim; the required data is stated.

The design favours an honest unavailable result over a precise-looking fabrication.
It never estimates a percentage of actual fake followers from aggregate public data.
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse


VALID_STATUSES = {"observed", "calculated", "modelled", "unavailable"}
INELIGIBLE_ROLES = {
    "candidate", "independent_evidence", "platform_navigation", "rejected",
    "withheld", "conflicted",
}
PRIMARY_ROLES = {"", "primary"}
EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])", re.I)
SPONSOR_MARKER_RE = re.compile(
    r"(?:#ad\b|#sponsored\b|paid\s+partnership|sponsored\s+by|"
    r"in\s+partnership\s+with|collab(?:oration)?\s+with)", re.I,
)
BRAND_AFTER_MARKER_RE = re.compile(
    r"(?:sponsored\s+by|in\s+partnership\s+with|collab(?:oration)?\s+with)\s+"
    r"([A-Za-z0-9][A-Za-z0-9&.'-]*(?:\s+[A-Za-z0-9][A-Za-z0-9&.'-]*){0,3})",
    re.I,
)
CONTACT_RAW_FIELDS = ("public_email", "business_email", "contact_email")
PHONE_RAW_FIELDS = ("public_business_phone", "business_phone")


@dataclass(frozen=True)
class EvidenceRef:
    """One attributable input used by a metric."""

    source_url: str
    source_type: str
    field: str
    value: Any = None
    note: str = ""


@dataclass(frozen=True)
class AgencyMetric:
    """Auditable contract for a single agency-facing result."""

    name: str
    status: str
    value: Any
    confidence: float
    interpretation: str
    formula: str
    denominator: str
    evidence: tuple[EvidenceRef, ...] = ()
    limitations: tuple[str, ...] = ()
    data_required: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"invalid claim status: {self.status}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return _plain(asdict(self))


@dataclass(frozen=True)
class AgencyIntelligence:
    """Complete, renderer-ready agency intelligence payload."""

    methodology_version: str
    audience_quality: AgencyMetric
    demographics: AgencyMetric
    fake_follower_anomaly: AgencyMetric
    interests: AgencyMetric
    engagement: AgencyMetric
    audience_overlap: AgencyMetric
    lookalike_creators: AgencyMetric
    contact_details: AgencyMetric
    estimated_reach: AgencyMetric
    brand_collaborations: AgencyMetric
    influence_score: AgencyMetric
    audience_insights: AgencyMetric
    brand_affinity: AgencyMetric
    historical_performance: AgencyMetric

    def to_dict(self) -> dict[str, Any]:
        return _plain(asdict(self))


def _plain(value: Any) -> Any:
    """Convert dataclass/enum/date containers to stable JSON-ready primitives."""
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    return value


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _items(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    if isinstance(value, Mapping):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) and out >= 0 else None


def _status(value: Any) -> str:
    raw = _get(value, "status", "unavailable")
    raw = getattr(raw, "value", raw)
    raw = str(raw).lower()
    if raw == "estimated":
        raw = "modelled"
    return raw if raw in VALID_STATUSES else "unavailable"


def _role(account: Any) -> str:
    raw = _get(account, "raw", {}) or {}
    return str(_get(raw, "identity_role", "primary") or "primary").lower()


def _eligible_accounts(raw: Any, *, primary_only: bool = False) -> list[Any]:
    out: list[Any] = []
    for account in _items(_get(raw, "accounts", [])):
        account_raw = _get(account, "raw", {}) or {}
        role = _role(account)
        if _get(account_raw, "analysis_eligible", True) is False or role in INELIGIBLE_ROLES:
            continue
        if primary_only and role not in PRIMARY_ROLES:
            continue
        out.append(account)
    return sorted(out, key=lambda a: (
        str(_get(a, "platform", "")), str(_get(a, "handle", "") or "").lower(),
        str(_get(a, "url", "")),
    ))


def _content_rows(raw: Any, *, primary_only: bool = False) -> list[tuple[Any, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    rows: list[tuple[Any, Any]] = []
    for account in _eligible_accounts(raw, primary_only=primary_only):
        for item in _items(_get(account, "content", [])):
            published = _get(item, "published_at")
            published_key = published.isoformat() if isinstance(published, datetime) else str(published or "")
            key = (
                str(_get(item, "platform", _get(account, "platform", ""))),
                str(_get(item, "url", "") or ""), str(_get(item, "title", "") or ""),
                published_key,
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append((account, item))
    return sorted(rows, key=lambda pair: (
        str(_get(pair[1], "platform", "")), str(_get(pair[1], "url", "") or ""),
        str(_get(pair[1], "title", "") or ""),
    ))


def _percentile(values: Sequence[float], q: float) -> float:
    xs = sorted(float(x) for x in values)
    if not xs:
        raise ValueError("percentile requires a non-empty sample")
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * min(1.0, max(0.0, q))
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _round_pct(value: float) -> float:
    return round(value * 100, 3)


def _ev(account: Any, field_name: str, value: Any, note: str = "") -> EvidenceRef:
    return EvidenceRef(
        source_url=str(_get(account, "url", "") or ""),
        source_type=str(_get(account, "platform", "public account")),
        field=field_name,
        value=_plain(value),
        note=note,
    )


def _unavailable(name: str, interpretation: str, data_required: Sequence[str], *,
                 limitations: Sequence[str] = (), denominator: str = "No valid observations") -> AgencyMetric:
    return AgencyMetric(
        name=name, status="unavailable", value=None, confidence=0.0,
        interpretation=interpretation, formula="Not calculated", denominator=denominator,
        limitations=tuple(limitations), data_required=tuple(data_required),
    )


def demographic_evidence(audience: Any) -> AgencyMetric:
    """Summarise demographic distributions without upgrading modelled priors to facts."""
    dimensions = (
        "age", "gender", "city_tier", "country_split", "top_cities", "device",
        "occupation", "education_mix", "career_mix", "income", "language",
    )
    reported: list[dict[str, Any]] = []
    statuses: list[str] = []
    evidence: list[EvidenceRef] = []
    for name in dimensions:
        obj = _get(audience, name)
        if obj is None:
            continue
        entries = _items(obj) if name == "country_split" else [obj]
        for entry in entries:
            status = _status(entry)
            buckets = _get(entry, "buckets")
            value = _get(entry, "value")
            if buckets:
                clean = {str(k): float(v) for k, v in buckets.items() if _number(v) is not None}
                total = sum(clean.values())
                value = ({k: round(v / total * 100, 1) for k, v in sorted(clean.items())}
                         if total > 0 else None)
            if status == "unavailable" or value in (None, {}, []):
                continue
            statuses.append(status)
            reported.append({
                "dimension": name, "status": status, "value": _plain(value),
                "sample_size": _get(entry, "sample_size"),
                "method": str(_get(entry, "method", "") or ""),
                "reasoning": str(_get(entry, "reasoning", "") or ""),
            })
            for source in _items(_get(entry, "evidence", [])):
                evidence.append(EvidenceRef(
                    source_url=str(_get(source, "source_url", "") or ""),
                    source_type="audience evidence", field=name, value=_plain(value),
                    note=str(_get(source, "note", "") or ""),
                ))
    if not reported:
        return _unavailable(
            "Demographic evidence", "No attributable audience demographic distribution was available.",
            ("Dated first-party platform audience exports for age, gender and geography",
             "Survey sample frame, response count and weighting method for survey-derived fields"),
            limitations=("Creator content topics and language are not audience demographics.",),
        )
    overall = "observed" if "observed" in statuses else "modelled"
    observed_n = sum(s == "observed" for s in statuses)
    confidence = min(0.95, 0.45 + 0.08 * observed_n) if overall == "observed" else 0.3
    return AgencyMetric(
        name="Demographic evidence", status=overall, value=reported,
        confidence=round(confidence, 2),
        interpretation=("Observed and modelled dimensions remain separately labelled; modelled "
                        "distributions are hypotheses, not platform analytics."),
        formula="Normalise each supplied bucket distribution to 100%; do not impute missing dimensions",
        denominator=f"{len(reported)} attributable demographic dimension(s)",
        evidence=tuple(sorted(evidence, key=lambda e: (e.source_url, e.field, str(e.value)))),
        limitations=("Public profiles do not expose a representative audience demographic sample.",),
        data_required=("Dated first-party export for every dimension still missing or modelled",),
    )


def engagement_metrics(raw: Any) -> AgencyMetric:
    """Calculate interaction rates only where both numerator and denominator are public."""
    measured: list[dict[str, Any]] = []
    evidence: list[EvidenceRef] = []
    eligible_rows = _content_rows(raw)
    for account, item in eligible_rows:
        views = _number(_get(item, "views"))
        likes = _number(_get(item, "likes"))
        comments = _number(_get(item, "comments"))
        if views is None or views <= 0 or (likes is None and comments is None):
            continue
        interactions = (likes or 0.0) + (comments or 0.0)
        measured.append({
            "platform": str(_get(item, "platform", _get(account, "platform", ""))),
            "views": views, "interactions": interactions,
            "rate": interactions / views, "account": account, "item": item,
        })
        evidence.append(_ev(account, "content interactions/views", {
            "content_url": _get(item, "url"), "views": views,
            "likes": likes, "comments": comments,
        }))
    if not measured:
        return _unavailable(
            "Public engagement", "No content item had a positive public view denominator and a like or comment numerator.",
            ("Post-level views or reach plus likes, comments, saves and shares for the same dated items",),
            limitations=("Follower totals alone are not engagement.",),
            denominator=f"0 valid items out of {len(eligible_rows)} collected eligible item(s)",
        )
    rates = [row["rate"] for row in measured]
    total_views = sum(row["views"] for row in measured)
    total_interactions = sum(row["interactions"] for row in measured)
    by_platform: list[dict[str, Any]] = []
    for platform in sorted({row["platform"] for row in measured}):
        rows = [row for row in measured if row["platform"] == platform]
        platform_views = sum(row["views"] for row in rows)
        platform_interactions = sum(row["interactions"] for row in rows)
        by_platform.append({
            "platform": platform, "items": len(rows),
            "weighted_interaction_rate_pct": round(platform_interactions / platform_views * 100, 3),
            "median_item_interaction_rate_pct": round(statistics.median(r["rate"] for r in rows) * 100, 3),
        })
    value = {
        "items": len(measured),
        "eligible_items": len(eligible_rows),
        "total_public_views": int(total_views),
        "total_public_interactions": int(total_interactions),
        "weighted_interaction_rate_pct": round(total_interactions / total_views * 100, 3),
        "median_item_interaction_rate_pct": round(statistics.median(rates) * 100, 3),
        "item_rate_p25_p75_pct": [round(_percentile(rates, .25) * 100, 3),
                                   round(_percentile(rates, .75) * 100, 3)],
        "by_platform": by_platform,
    }
    return AgencyMetric(
        name="Public engagement", status="calculated", value=value,
        confidence=round(min(0.9, 0.45 + .03 * min(len(measured), 15)), 2),
        interpretation=("Interactions divided by public item views in the collected sample; "
                        "this is not unique-person engagement or platform reach."),
        formula="100 × Σ(public likes + public comments) / Σ(public views)",
        denominator=f"{int(total_views):,} public views across {len(measured)} item(s)",
        evidence=tuple(evidence[:30]),
        limitations=("Saves, shares, private interactions and uncollected posts are absent.",
                     "Lifetime views are not a fixed-age or random sample."),
        data_required=("First-party post reach/impressions and all interaction types for campaign-grade engagement",),
    )


def interest_evidence(signals: Any, audience: Any = None) -> AgencyMetric:
    """Report content-topic affinity as a proxy, never as observed audience interest."""
    ranked = []
    for entry in _items(_get(signals, "topic_rank", [])):
        if isinstance(entry, (tuple, list)) and len(entry) >= 2:
            topic, share = entry[0], _number(entry[1])
        else:
            topic, share = _get(entry, "topic"), _number(_get(entry, "share"))
        if topic and share is not None and share > 0:
            ranked.append((str(topic), share))
    ranked.sort(key=lambda row: (-row[1], row[0]))
    if not ranked:
        return _unavailable(
            "Audience interest evidence", "No stable content-topic vector was available.",
            ("A representative public content sample or first-party audience interest export",),
            limitations=("Profile keywords alone are insufficient to infer audience interest.",),
        )
    total = sum(score for _, score in ranked) or 1.0
    values = [{"topic": topic, "content_share_pct": round(score / total * 100, 1)}
              for topic, score in ranked[:10]]
    hits = int(_number(_get(signals, "topic_evidence_total")) or 0)
    terms = int(_number(_get(signals, "topic_distinct_terms")) or 0)
    confidence = min(.7, .25 + min(hits, 20) * .015 + min(terms, 10) * .02)
    return AgencyMetric(
        name="Audience interest evidence", status="modelled", value=values,
        confidence=round(confidence, 2),
        interpretation=("These are creator-content topic shares and therefore an audience-interest "
                        "hypothesis, not a measurement of followers' off-platform interests."),
        formula="topic term hits / all classified topic term hits",
        denominator=f"{hits} classified term hit(s) across {terms} distinct term(s)",
        limitations=("Watching content does not establish enduring interest or purchase intent.",),
        data_required=("First-party interest/affinity export or a consented, weighted audience survey",),
    )


def _comment_value(comments: Any, key: str) -> float | None:
    if not _get(comments, "available", False):
        return None
    return _number(_get(comments, key))


def audience_quality_proxy(raw: Any, engagement: AgencyMetric, comments: Any = None) -> AgencyMetric:
    """Transparent public-signal rubric; not a judgement of real people or follower validity."""
    components: list[dict[str, Any]] = []
    weighted = 0.0
    available_weight = 0.0

    if engagement.status == "calculated":
        eligible = int(engagement.value["eligible_items"] or 0)
        measured = int(engagement.value["items"] or 0)
        score = measured / eligible * 100 if eligible else 0.0
        components.append({"component": "interaction-data coverage", "score": round(score, 1), "weight": 25,
                           "basis": f"{measured}/{eligible} eligible items have compatible public counts"})
        weighted += score * .25
        available_weight += .25

    sample_n = int(_comment_value(comments, "sample_size") or 0)
    duplicate = _comment_value(comments, "duplicate_rate")
    top_author = _comment_value(comments, "top_author_share")
    if sample_n >= 20 and duplicate is not None:
        score = max(0.0, 100.0 - duplicate)
        components.append({"component": "sampled comment text originality", "score": round(score, 1), "weight": 30,
                           "basis": f"100 − {duplicate:g}% exact duplicate-text rate; n={sample_n}"})
        weighted += score * .30
        available_weight += .30
    if sample_n >= 20 and top_author is not None:
        score = max(0.0, 100.0 - top_author)
        components.append({"component": "sampled commenter dispersion", "score": round(score, 1), "weight": 25,
                           "basis": f"100 − {top_author:g}% top named-author share; n={sample_n}"})
        weighted += score * .25
        available_weight += .25

    ratio_values: list[float] = []
    for account in _eligible_accounts(raw, primary_only=True):
        followers = _number(_get(account, "followers"))
        views = [_number(_get(item, "views")) for item in _items(_get(account, "content", []))]
        views = [v for v in views if v is not None and v > 0]
        if followers and len(views) >= 4:
            ratio_values.append(statistics.median(views) / followers)
    if ratio_values:
        ratio = statistics.median(ratio_values)
        # Descriptive rubric, intentionally capped and never called audience authenticity.
        score = min(100.0, 25.0 + 750.0 * ratio)
        components.append({"component": "median public views/followers scale", "score": round(score, 1), "weight": 20,
                           "basis": f"median account ratio {ratio * 100:.3f}%"})
        weighted += score * .20
        available_weight += .20

    if available_weight < .45 or len(components) < 2:
        return _unavailable(
            "Public audience-signal quality proxy",
            "Too few independent public-signal dimensions support an audience-quality screen.",
            ("Post-level interaction counts", "At least 20 public comments with author identifiers",
             "First-party unique reach, retention and follower-growth history"),
            limitations=("Audience quality and follower authenticity cannot be established from follower totals.",),
            denominator=f"{len(components)} usable proxy component(s); {round(available_weight * 100)}% rubric coverage",
        )
    central = weighted / available_weight
    width = 8 + 25 * (1 - available_weight)
    low, high = max(0, round(central - width)), min(100, round(central + width))
    label = "stronger public signals" if central >= 70 else "mixed public signals" if central >= 45 else "weaker public signals"
    return AgencyMetric(
        name="Public audience-signal quality proxy", status="modelled",
        value={"score": round(central), "uncertainty_range": [low, high], "label": label,
               "component_coverage_pct": round(available_weight * 100), "components": components},
        confidence=round(min(.65, .25 + .4 * available_weight), 2),
        interpretation=("A public-data diligence screen, not a measure of follower authenticity, "
                        "buyer quality, brand safety or unique audience quality."),
        formula="weighted mean of available rubric components, renormalised by covered weight",
        denominator=f"{len(components)} public proxy component(s); {round(available_weight * 100)}% rubric coverage",
        limitations=("Rubric thresholds are decision heuristics, not a validated population model.",
                     "Public comments and posts are selected, not probability samples."),
        data_required=("First-party reach, retention, follower-growth and audience-integrity exports",),
    )


def fake_follower_anomaly_screen(raw: Any, comments: Any = None) -> AgencyMetric:
    """Screen public anomalies without estimating an actual fake-follower percentage."""
    indicators: list[dict[str, Any]] = []
    weighted_risk = 0.0
    available_weight = 0.0

    ratios: list[float] = []
    ratio_items = 0
    for account in _eligible_accounts(raw, primary_only=True):
        followers = _number(_get(account, "followers"))
        views = [_number(_get(item, "views")) for item in _items(_get(account, "content", []))]
        views = [v for v in views if v is not None and v > 0]
        if followers and len(views) >= 6:
            ratios.append(statistics.median(views) / followers)
            ratio_items += len(views)
    if ratios:
        ratio = statistics.median(ratios)
        risk = 80.0 if ratio < .005 else 60.0 if ratio < .02 else 30.0 if ratio < .05 else 10.0
        indicators.append({"indicator": "median public views/follower ratio", "value_pct": round(ratio * 100, 3),
                           "risk_points": risk, "weight": 50, "items": ratio_items})
        weighted_risk += risk * .50
        available_weight += .50

    sample_n = int(_comment_value(comments, "sample_size") or 0)
    duplicate = _comment_value(comments, "duplicate_rate")
    top_author = _comment_value(comments, "top_author_share")
    if sample_n >= 30 and duplicate is not None:
        risk = min(100.0, duplicate * 3.0)
        indicators.append({"indicator": "exact duplicate comment-text rate", "value_pct": duplicate,
                           "risk_points": round(risk, 1), "weight": 30, "sample_size": sample_n})
        weighted_risk += risk * .30
        available_weight += .30
    if sample_n >= 30 and top_author is not None:
        risk = min(100.0, max(0.0, (top_author - 5.0) * 4.0))
        indicators.append({"indicator": "top named-author concentration", "value_pct": top_author,
                           "risk_points": round(risk, 1), "weight": 20, "sample_size": sample_n})
        weighted_risk += risk * .20
        available_weight += .20

    if available_weight < .7 or len(indicators) < 2:
        return _unavailable(
            "Public follower-anomaly risk screen",
            "Public evidence is insufficient for a multi-signal anomaly screen; no fake-follower percentage is estimated.",
            ("Follower-growth time series", "Reach and impressions by follower/non-follower",
             "A representative follower audit or platform integrity report",
             "At least 30 attributable public comments for repetition/concentration checks"),
            limitations=("Low views can reflect distribution, topic, cadence or format rather than inauthentic followers.",),
            denominator=f"{len(indicators)} usable indicator(s); {round(available_weight * 100)}% screen coverage",
        )
    central = weighted_risk / available_weight
    width = 12 + 25 * (1 - available_weight)
    low, high = max(0, round(central - width)), min(100, round(central + width))
    band = "higher anomaly risk" if central >= 65 else "moderate anomaly risk" if central >= 35 else "lower anomaly risk"
    return AgencyMetric(
        name="Public follower-anomaly risk screen", status="modelled",
        value={"risk_score_range": [low, high], "central_risk_score": round(central),
               "risk_band": band, "estimated_fake_follower_percent": None,
               "indicator_coverage_pct": round(available_weight * 100), "indicators": indicators},
        confidence=round(min(.6, .25 + .35 * available_weight), 2),
        interpretation=("The range is a heuristic anomaly-risk score from 0–100. It is not "
                        "the share or count of fake followers and cannot identify individuals."),
        formula="weighted mean of public anomaly indicators, renormalised by available weight",
        denominator=f"{len(indicators)} indicator(s); {round(available_weight * 100)}% screen coverage",
        limitations=("Association is not diagnosis; benign content-distribution effects can produce the same signals.",
                     "Comment samples are relevance-ranked and may not represent all viewers."),
        data_required=("Platform integrity export or audited follower sample to estimate actual invalid-follow rate",),
    )


def public_contacts(raw: Any) -> AgencyMetric:
    """Extract only public contacts from verified creator/owned surfaces, never press pages."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    evidence: list[EvidenceRef] = []
    for account in _eligible_accounts(raw):
        source_url = str(_get(account, "url", "") or "")
        platform = str(_get(account, "platform", "") or "")
        relationship = _role(account)
        bio = str(_get(account, "bio", "") or "")
        for email in EMAIL_RE.findall(bio):
            value = email.lower()
            found[("email", value)] = {"type": "email", "value": value,
                                        "source_url": source_url, "platform": platform,
                                        "relationship": relationship, "provenance": "observed_public"}
            evidence.append(_ev(account, "bio.email", value))
        account_raw = _get(account, "raw", {}) or {}
        for field_name in CONTACT_RAW_FIELDS:
            for raw_value in _items(_get(account_raw, field_name)):
                for email in EMAIL_RE.findall(str(raw_value or "")):
                    value = email.lower()
                    found[("email", value)] = {"type": "email", "value": value,
                                                "source_url": source_url, "platform": platform,
                                                "relationship": relationship, "provenance": "observed_public"}
                    evidence.append(_ev(account, f"raw.{field_name}", value))
        for field_name in PHONE_RAW_FIELDS:
            for raw_value in _items(_get(account_raw, field_name)):
                value = re.sub(r"\s+", " ", str(raw_value or "")).strip()
                if value:
                    found[("business_phone", value)] = {
                        "type": "business_phone", "value": value, "source_url": source_url,
                        "platform": platform, "relationship": relationship,
                        "provenance": "explicit_public_business_field",
                    }
                    evidence.append(_ev(account, f"raw.{field_name}", value))
        for link in _items(_get(account, "external_links", [])):
            link = str(link or "").strip()
            low = link.lower()
            if low.startswith("mailto:"):
                email = low[7:].split("?", 1)[0]
                if EMAIL_RE.fullmatch(email):
                    found[("email", email)] = {"type": "email", "value": email,
                                                "source_url": source_url, "platform": platform,
                                                "relationship": relationship, "provenance": "observed_public"}
                    evidence.append(_ev(account, "external_links.mailto", email))
            elif ("wa.me/" in low or "api.whatsapp.com/" in low or
                  re.search(r"/(?:contact|contact-us|book|booking)(?:[/?#]|$)", low)):
                canonical = link.split("#", 1)[0]
                found[("contact_url", canonical)] = {
                    "type": "contact_url", "value": canonical, "source_url": source_url,
                    "platform": platform, "relationship": relationship,
                    "provenance": "observed_public",
                }
                evidence.append(_ev(account, "external_links.contact", canonical))
    type_order = {"email": 0, "contact_url": 1, "business_phone": 2}
    contacts = sorted(found.values(), key=lambda row: (
        type_order.get(str(row["type"]), 9), str(row["value"]).lower(),
        str(row["source_url"]),
    ))
    if not contacts:
        return _unavailable(
            "Public contact details", "No public business email or contact route was found on an attributable creator-owned surface.",
            ("Creator-approved business email, media-kit URL or contact form",),
            limitations=("Search-result snippets and independent press pages are excluded from contact attribution.",),
        )
    return AgencyMetric(
        name="Public contact details", status="observed", value=contacts,
        confidence=.9, interpretation="Publicly published routes only; verify ownership and consent before outreach.",
        formula="Exact extraction and canonical deduplication from eligible creator/owned surfaces",
        denominator=f"{len(_eligible_accounts(raw))} eligible account/property surface(s)",
        evidence=tuple(sorted(evidence, key=lambda e: (e.source_url, e.field, str(e.value)))),
        limitations=("A public address is not consent for bulk or automated outreach.",
                     "Personal phone numbers are not inferred from free text."),
        data_required=("Current creator-approved media kit for commercial routing and regional consent requirements",),
    )


def estimated_reachable_impressions(raw: Any) -> AgencyMetric:
    """Model a per-placement delivery range from comparable primary-account public views."""
    rows = _content_rows(raw, primary_only=True)
    measured = [(account, item, _number(_get(item, "views"))) for account, item in rows]
    measured = [(a, i, v) for a, i, v in measured if v is not None and v > 0]
    latest = [(a, i, v) for a, i, v in measured
              if "latest" in _items(_get(_get(i, "raw", {}) or {}, "sample", []))
              or str(_get(_get(i, "raw", {}) or {}, "sort", "")).lower() == "latest"]
    sample = latest if len(latest) >= 4 else measured
    if len(sample) < 4:
        return _unavailable(
            "Estimated reachable impressions", "Fewer than four comparable primary-account items have public delivery counts.",
            ("At least four comparable recent posts with reach/impressions from the intended placement format",),
            limitations=("Follower count is not substituted for reachable impressions.",),
            denominator=f"{len(sample)} valid public view observation(s)",
        )
    views = [row[2] for row in sample]
    lower, centre, upper = round(_percentile(views, .25)), round(_percentile(views, .5)), round(_percentile(views, .75))
    evidence = tuple(_ev(a, "content.views", {"content_url": _get(i, "url"), "views": int(v)})
                     for a, i, v in sample[:30])
    return AgencyMetric(
        name="Estimated reachable impressions", status="modelled",
        value={"per_placement_range": [lower, upper], "central_public_view_proxy": centre,
               "sample_size": len(sample), "sample_scope": "explicit latest sample" if sample is latest else "all collected primary-account items"},
        confidence=round(min(.7, .35 + .025 * min(len(sample), 12)), 2),
        interpretation=("An empirical public-view delivery proxy for one placement. Public views "
                        "are not ad impressions, unique reach, guaranteed delivery or cross-platform people."),
        formula="lower=P25(public views), central=median(public views), upper=P75(public views)",
        denominator=f"{len(sample)} comparable primary-account item(s) with positive public views",
        evidence=evidence,
        limitations=("Content age, topic, format, paid distribution and sponsorship effect are uncontrolled.",
                     "Do not sum platforms without a deduplicated reach study."),
        data_required=("First-party sponsored-post reach/impressions for the same format and placement window",),
    )


def _brand_values(value: Any) -> list[str]:
    out: list[str] = []
    for entry in _items(value):
        if isinstance(entry, Mapping):
            candidate = (_get(entry, "brand") or _get(entry, "name") or
                         _get(entry, "partner") or _get(entry, "sponsor"))
        else:
            candidate = entry
        candidate = re.sub(r"\s+", " ", str(candidate or "")).strip(" .,#@")
        if candidate and len(candidate) <= 80:
            out.append(candidate)
    return out


def brand_collaboration_evidence(raw: Any) -> AgencyMetric:
    """Collect explicit paid-partnership/collaboration markers from eligible surfaces."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    evidence: list[EvidenceRef] = []
    for account in _eligible_accounts(raw):
        account_raw = _get(account, "raw", {}) or {}
        for brand in _brand_values(_get(account_raw, "brand_collaborations")):
            key = (brand.lower(), str(_get(account, "url", "")))
            found[key] = {"brand": brand, "source_url": key[1], "platform": _get(account, "platform"),
                          "relationship": _role(account), "basis": "explicit account collaboration field"}
            evidence.append(_ev(account, "raw.brand_collaborations", brand))
        for item in _items(_get(account, "content", [])):
            item_raw = _get(item, "raw", {}) or {}
            title = str(_get(item, "title", "") or "")
            explicit_marker = bool(SPONSOR_MARKER_RE.search(title) or
                                   _get(item_raw, "paid_partnership", False) or
                                   _get(item_raw, "sponsored", False))
            brands: list[str] = []
            explicit_fields = ("sponsor", "sponsors", "paid_partner")
            for field_name in explicit_fields:
                brands.extend(_brand_values(_get(item_raw, field_name)))
            # Generic content tagging fields can describe a mere mention.  Promote them
            # only when an independent paid-partnership/sponsorship marker is present.
            if explicit_marker:
                for field_name in ("brand", "brand_name", "partner"):
                    brands.extend(_brand_values(_get(item_raw, field_name)))
            if explicit_marker and not brands:
                match = BRAND_AFTER_MARKER_RE.search(title)
                if match:
                    brands.append(match.group(1).strip())
            item_url = str(_get(item, "url", "") or _get(account, "url", ""))
            if explicit_marker and not brands:
                brands = ["brand not named"]
            for brand in sorted(set(brands), key=str.lower):
                basis = ("explicit structured sponsorship field" if any(
                    _get(item_raw, f) for f in explicit_fields
                ) else "explicit sponsorship marker in content")
                key = (brand.lower(), item_url)
                found[key] = {"brand": brand, "source_url": item_url,
                              "platform": _get(item, "platform", _get(account, "platform")),
                              "relationship": _role(account), "basis": basis}
                evidence.append(_ev(account, "content.explicit_collaboration",
                                    {"brand": brand, "content_url": item_url}))
    collaborations = [found[key] for key in sorted(found)]
    if not collaborations:
        return _unavailable(
            "Public brand collaborations", "No explicit paid-partnership, sponsorship or collaboration marker was observed.",
            ("Creator media kit or dated campaign wrap reports", "Platform paid-partnership labels/API fields"),
            limitations=("A brand mention or press article is not treated as a collaboration.",),
        )
    named = sorted({row["brand"] for row in collaborations if row["brand"] != "brand not named"}, key=str.lower)
    return AgencyMetric(
        name="Public brand collaborations", status="observed",
        value={"collaborations": collaborations, "named_brands": named,
               "explicit_items": len(collaborations)}, confidence=.85,
        interpretation="Only explicit public sponsorship/collaboration markers are listed; commercial terms and outcomes remain unknown.",
        formula="Deduplicate explicit (brand, source URL) pairs",
        denominator=f"{len(_eligible_accounts(raw))} eligible account/property surface(s)",
        evidence=tuple(sorted(evidence, key=lambda e: (e.source_url, str(e.value)))),
        limitations=("Absence of a public label is not evidence that no collaboration occurred.",
                     "Brand mentions without a partnership marker are excluded."),
        data_required=("Campaign contract, dates, deliverables and first-party outcome report for performance claims",),
    )


def _candidate_rows(competitors: Any) -> list[Any]:
    rows = _get(competitors, "competitors", competitors)
    return _items(rows)


def rank_lookalike_creators(signals: Any, competitors: Any, *, limit: int = 10) -> list[dict[str, Any]]:
    """Rank creator candidates by transparent public similarity features.

    ``content_overlap`` is expected on a 0–100 scale. Missing features are omitted and
    weights are renormalised, while ``feature_coverage_pct`` prevents a thin candidate
    from looking as well-supported as a complete one.
    """
    subject_followers = _number(_get(signals, "total_audience"))
    subject_platforms = {str(k) for k, v in (_get(signals, "followers", {}) or {}).items()
                         if _number(v) and _number(v) > 0}
    ranked: list[dict[str, Any]] = []
    for candidate in _candidate_rows(competitors):
        handle = str(_get(candidate, "handle", "") or "").strip()
        if not handle:
            continue
        parts: list[tuple[str, float, float]] = []
        overlap = _number(_get(candidate, "content_overlap"))
        if overlap is not None:
            parts.append(("content_topic_overlap", min(100.0, overlap), .55))
        followers = _number(_get(candidate, "followers"))
        if followers and subject_followers:
            distance = abs(math.log10(followers / subject_followers))
            parts.append(("public_scale_similarity", max(0.0, 100.0 - distance / 3.0 * 100.0), .30))
        platform = str(_get(candidate, "platform", "") or "")
        if platform:
            parts.append(("platform_match", 100.0 if platform in subject_platforms else 0.0, .15))
        if not parts:
            continue
        covered = sum(weight for _, _, weight in parts)
        score = sum(value * weight for _, value, weight in parts) / covered
        ranked.append({
            "handle": handle, "display_name": _get(candidate, "display_name"),
            "platform": platform, "url": _get(candidate, "url"),
            "lookalike_score": round(score, 1), "feature_coverage_pct": round(covered * 100),
            "features": [{"name": name, "score": round(value, 1), "weight": round(weight * 100)}
                         for name, value, weight in parts],
            "scope": "creator/topic/scale similarity; not shared followers",
        })
    ranked.sort(key=lambda row: (-row["lookalike_score"], -row["feature_coverage_pct"],
                                 str(row["handle"]).lower(), str(row["url"] or "")))
    return ranked[:max(0, int(limit))]


def lookalike_metric(signals: Any, competitors: Any) -> AgencyMetric:
    rows = rank_lookalike_creators(signals, competitors)
    if not rows:
        return _unavailable(
            "Lookalike creators", "No attributable competitor candidates had usable similarity features.",
            ("Topic-matched creator candidates with public profile data",),
            limitations=("Creator similarity is not audience overlap.",),
        )
    return AgencyMetric(
        name="Lookalike creators", status="modelled", value=rows,
        confidence=round(min(.75, .35 + .04 * min(len(rows), 8)), 2),
        interpretation="Ranked public creator similarity for planning; no shared-follower claim is made.",
        formula="renormalised 55% topic overlap + 30% log-scale similarity + 15% platform match",
        denominator=f"{len(rows)} candidate creator(s) with at least one usable feature",
        limitations=("Search discovery is not a complete market frame.",
                     "Lexical topic overlap does not measure audience identity or campaign substitution."),
        data_required=("Privacy-safe audience-overlap or panel data to validate lookalikes",),
    )


def audience_overlap_metric(signals: Any, competitors: Any) -> AgencyMetric:
    lookalikes = rank_lookalike_creators(signals, competitors)
    affinity = [{"handle": row["handle"], "topic_scale_affinity_score": row["lookalike_score"],
                 "feature_coverage_pct": row["feature_coverage_pct"]} for row in lookalikes]
    if not affinity:
        return _unavailable(
            "Audience overlap", "Exact shared-person overlap is unavailable and no topic-affinity proxy could be calculated.",
            ("Privacy-safe matched audience counts with universe and intersection denominators",),
            limitations=("Public follower totals cannot identify unique people across accounts.",),
        )
    return AgencyMetric(
        name="Audience overlap", status="modelled",
        value={"exact_shared_audience_pct": None, "exact_overlap_status": "unavailable",
               "topic_scale_affinity_proxy": affinity}, confidence=.35,
        interpretation=("Exact audience overlap is unavailable. The proxy ranks topical and "
                        "public-scale affinity only; it does not estimate shared followers."),
        formula="lookalike feature score; exact overlap not calculated",
        denominator=f"{len(affinity)} public creator candidate(s); no shared-person denominator",
        limitations=("Topic similarity, public scale and platform match do not identify the same people.",),
        data_required=("Privacy-safe matched audience intersection and union counts for the same dated period",),
    )


TOPIC_BRAND_CATEGORIES = {
    "finance": "financial services and fintech", "career": "jobs, learning and careers",
    "career_finance": "financial services and careers", "exam": "education and test preparation",
    "exam_prep": "education and test preparation", "education": "education and learning",
    "admission": "education and admissions", "technology": "technology and software",
    "ai": "AI and productivity software", "fitness": "fitness and wellness",
    "beauty": "beauty and personal care", "fashion": "fashion and lifestyle",
    "travel": "travel and hospitality", "food": "food and beverages",
    "business": "business services and entrepreneurship",
}


def brand_affinity_metric(interests: AgencyMetric, collaborations: AgencyMetric) -> AgencyMetric:
    explicit = []
    if collaborations.status == "observed":
        explicit = list(collaborations.value.get("named_brands", []))
    categories: list[dict[str, Any]] = []
    if interests.status == "modelled":
        for row in interests.value:
            topic = str(row.get("topic", "")).lower()
            category = next((label for key, label in TOPIC_BRAND_CATEGORIES.items() if key in topic), None)
            if category:
                categories.append({"category": category,
                                   "content_affinity_pct": row.get("content_share_pct"),
                                   "basis_topic": row.get("topic")})
    unique_categories: dict[str, dict[str, Any]] = {}
    for row in categories:
        existing = unique_categories.get(row["category"])
        if existing is None or (row["content_affinity_pct"] or 0) > (existing["content_affinity_pct"] or 0):
            unique_categories[row["category"]] = row
    categories = [unique_categories[k] for k in sorted(unique_categories)]
    if not explicit and not categories:
        return _unavailable(
            "Brand affinity", "No explicit collaboration history or stable content-category proxy was available.",
            ("Dated collaboration history", "Audience brand-affinity study or purchase-index data"),
            limitations=("Audience brand preference cannot be inferred from creator identity alone.",),
        )
    status = "calculated" if explicit else "modelled"
    return AgencyMetric(
        name="Brand affinity", status=status,
        value={"explicit_collaboration_brands": explicit,
               "creator_content_category_proxy": categories,
               "audience_brand_preference": None},
        confidence=.75 if explicit else .35,
        interpretation=("Explicit brands describe creator collaboration history. Categories "
                        "describe creator content fit, not followers' brand preference or purchase behaviour."),
        formula="deduplicated explicit brands plus deterministic topic-to-category mapping",
        denominator=f"{len(explicit)} explicit brand(s), {len(categories)} content category proxy/proxies",
        limitations=("Historical sponsorship does not establish exclusivity, lift, safety or future fit.",),
        data_required=("Audience brand-lift, purchase-index or consented survey data for actual audience affinity",),
    )


def historical_performance_metric(raw: Any, content_analysis: Any = None) -> AgencyMetric:
    """Calculate trend only for exhaustive, fixed-age or equivalent comparable windows."""
    if (_get(content_analysis, "trend_eligible", False) and
            _number(_get(content_analysis, "current_median")) is not None and
            _number(_get(content_analysis, "catalogue_median"))):
        current = float(_get(content_analysis, "current_median"))
        historical = float(_get(content_analysis, "catalogue_median"))
        current_n = int(_number(_get(content_analysis, "current_sample")) or 0)
        historical_n = int(_number(_get(content_analysis, "historical_sample")) or 0)
        change = (current / historical - 1) * 100
        return AgencyMetric(
            name="Historical performance", status="calculated",
            value={"current_comparable_median_views": round(current),
                   "historical_comparable_median_views": round(historical),
                   "change_pct": round(change, 1), "current_sample": current_n,
                   "historical_sample": historical_n,
                   "direction": "up" if change > 2 else "down" if change < -2 else "flat"},
            confidence=round(min(.85, .45 + .02 * min(current_n + historical_n, 20)), 2),
            interpretation="Descriptive change between comparable fixed-age/exhaustive view windows; no causal explanation is assigned.",
            formula="100 × (current comparable median / historical comparable median − 1)",
            denominator=f"{current_n} current and {historical_n} historical comparable item(s)",
            limitations=("Topic, format and distribution changes remain potential confounders.",),
            data_required=("Platform reach/impression snapshots for attribution and campaign-level history",),
        )
    fixed_rows: list[tuple[datetime, float, int]] = []
    for _, item in _content_rows(raw, primary_only=True):
        views = _number(_get(item, "views"))
        published = _get(item, "published_at")
        age_days = _number(_get(_get(item, "raw", {}) or {}, "views_age_days"))
        if views is not None and views > 0 and isinstance(published, datetime) and age_days is not None:
            fixed_rows.append((published, views, int(age_days)))
    common_ages = sorted({age for _, _, age in fixed_rows})
    if len(fixed_rows) >= 8 and len(common_ages) == 1:
        fixed_rows.sort(key=lambda row: row[0])
        group_n = max(4, len(fixed_rows) // 3)
        older, current = fixed_rows[:group_n], fixed_rows[-group_n:]
        if (current[-1][0] - older[0][0]).days >= 60:
            old_med = statistics.median(row[1] for row in older)
            cur_med = statistics.median(row[1] for row in current)
            change = (cur_med / old_med - 1) * 100 if old_med else 0.0
            return AgencyMetric(
                name="Historical performance", status="calculated",
                value={"current_comparable_median_views": round(cur_med),
                       "historical_comparable_median_views": round(old_med),
                       "change_pct": round(change, 1), "current_sample": len(current),
                       "historical_sample": len(older), "views_age_days": common_ages[0],
                       "direction": "up" if change > 2 else "down" if change < -2 else "flat"},
                confidence=.65,
                interpretation="Descriptive fixed-age public-view comparison; no causal explanation is assigned.",
                formula="100 × (recent fixed-age median / older fixed-age median − 1)",
                denominator=f"{len(current)} recent and {len(older)} older items measured at {common_ages[0]} days",
                limitations=("Topic and format mix remain uncontrolled.",),
                data_required=("Campaign and channel analytics snapshots for a full historical series",),
            )
    dated = sum(isinstance(_get(item, "published_at"), datetime)
                for _, item in _content_rows(raw, primary_only=True))
    return _unavailable(
        "Historical performance",
        "A valid trend cannot be calculated from current lifetime views because older items have had longer to accumulate delivery.",
        ("Exhaustive content history measured at a common post age, or dated analytics snapshots",
         "Campaign impression/reach/click/conversion series with unchanged metric definitions"),
        limitations=("A popular-post sample is not a baseline and cannot establish growth or decline.",),
        denominator=f"{dated} dated item(s), but no eligible comparable historical window",
    )


def influence_score_metric(raw: Any, signals: Any, engagement: AgencyMetric,
                           quality: AgencyMetric, reach: AgencyMetric,
                           brand: Any = None) -> AgencyMetric:
    """Coverage-qualified planning index; missing components do not silently score zero."""
    components: list[dict[str, Any]] = []
    numerator = 0.0
    covered_weight = 0.0

    total_followers = _number(_get(signals, "total_audience"))
    if total_followers is None:
        total_followers = sum(_number(_get(a, "followers")) or 0
                              for a in _eligible_accounts(raw, primary_only=True))
    if total_followers and total_followers > 0:
        score = min(100.0, max(0.0, (math.log10(total_followers) - 3.0) / 4.0 * 100.0))
        components.append({"component": "public scale", "score": round(score, 1), "weight": 25,
                           "basis": f"log10({int(total_followers):,} summed primary-account follows)"})
        numerator += score * .25
        covered_weight += .25
    if engagement.status == "calculated":
        rate = float(engagement.value["weighted_interaction_rate_pct"])
        score = min(100.0, 20.0 * math.sqrt(max(0.0, rate)))
        components.append({"component": "public interaction/view rate", "score": round(score, 1), "weight": 25,
                           "basis": f"{rate:.3f}% weighted public rate"})
        numerator += score * .25
        covered_weight += .25
    if quality.status == "modelled":
        score = float(quality.value["score"])
        components.append({"component": "public audience-signal proxy", "score": round(score, 1), "weight": 15,
                           "basis": f"{quality.value['component_coverage_pct']}% proxy coverage"})
        numerator += score * .15
        covered_weight += .15
    if reach.status == "modelled":
        low, high = reach.value["per_placement_range"]
        score = 100.0 * low / high if high else 0.0
        components.append({"component": "sample delivery consistency", "score": round(score, 1), "weight": 15,
                           "basis": f"public view P25/P75={low:,}/{high:,}"})
        numerator += score * .15
        covered_weight += .15
    brand_total = _number(_get(brand, "total"))
    if brand_total is not None:
        max_brand = 10.0 * max(1, len(_items(_get(brand, "pillars", []))))
        score = min(100.0, brand_total / max_brand * 100.0)
        components.append({"component": "public brand-evidence rubric", "score": round(score, 1), "weight": 20,
                           "basis": f"{brand_total:g}/{max_brand:g} existing brand-rubric points"})
        numerator += score * .20
        covered_weight += .20
    if covered_weight < .5 or len(components) < 2:
        return _unavailable(
            "Influence score", "Fewer than half of the score's evidence weights are covered.",
            ("Public scale", "Comparable post-level engagement", "Delivery distribution",
             "Audience-quality evidence", "Attributable authority/trust evidence"),
            limitations=("Missing components are not treated as zero.",),
            denominator=f"{round(covered_weight * 100)}% component-weight coverage",
        )
    score = numerator / covered_weight
    return AgencyMetric(
        name="Influence score", status="modelled",
        value={"score": round(score), "component_coverage_pct": round(covered_weight * 100),
               "components": components, "decision_use": "shortlisting and diligence prioritisation only"},
        confidence=round(min(.7, .3 + .4 * covered_weight), 2),
        interpretation=("A coverage-qualified public-evidence planning index, not measured "
                        "brand lift, sales influence, audience authenticity or campaign ROI."),
        formula="Σ(component score × configured weight) / Σ(available configured weights)",
        denominator=f"{len(components)} component(s); {round(covered_weight * 100)}% score-weight coverage",
        limitations=("Weights are an explicit business rubric, not a statistically validated causal model.",
                     "Cross-platform public follows may contain the same people."),
        data_required=("Campaign lift, conversion and cost data to validate or recalibrate the rubric",),
    )


def audience_insight_metric(interests: AgencyMetric, engagement: AgencyMetric,
                            comments: Any, reach: AgencyMetric) -> AgencyMetric:
    insights: list[dict[str, Any]] = []
    if interests.status == "modelled" and interests.value:
        top = interests.value[0]
        insights.append({"insight": f"{str(top['topic']).replace('_', ' ')} leads the classified creator-content mix",
                         "status": "modelled", "value": top["content_share_pct"], "unit": "% of classified content-topic signal",
                         "decision": "Use as a creative hypothesis and validate with audience analytics or a survey."})
    if engagement.status == "calculated":
        platforms = engagement.value.get("by_platform", [])
        if platforms:
            best = sorted(platforms, key=lambda x: (-x["weighted_interaction_rate_pct"], x["platform"]))[0]
            insights.append({"insight": f"{best['platform']} has the highest measured interaction/view rate in the collected sample",
                             "status": "calculated", "value": best["weighted_interaction_rate_pct"], "unit": "%",
                             "decision": "Treat as a placement test hypothesis; formats and samples are not controlled."})
    if _get(comments, "available", False):
        buckets = sorted(_items(_get(comments, "buckets", [])),
                         key=lambda b: (-(_number(_get(b, "count")) or 0), str(_get(b, "label", ""))))
        if buckets:
            top = buckets[0]
            insights.append({"insight": f"{_get(top, 'label')} is the largest classified public-comment theme",
                             "status": "calculated", "value": _get(top, "share"), "unit": "% of sampled comments",
                             "decision": "Validate against a representative sample before audience-wide targeting."})
    if reach.status == "modelled":
        insights.append({"insight": "The public-view proxy supplies a testable per-placement delivery band",
                         "status": "modelled", "value": reach.value["per_placement_range"], "unit": "public views",
                         "decision": "Contract on first-party impressions/reach, not this proxy."})
    if not insights:
        return _unavailable(
            "Audience insights", "No evidence-qualified topic, interaction, comment or delivery insight was available.",
            ("Representative content and comments, plus first-party audience and reach analytics",),
        )
    statuses = {row["status"] for row in insights}
    status = "calculated" if "calculated" in statuses else "modelled"
    return AgencyMetric(
        name="Audience insights", status=status, value=insights,
        confidence=round(min(.7, .3 + .08 * len(insights)), 2),
        interpretation="Decision hypotheses tied to explicit public evidence; no causal or population-wide claim is made.",
        formula="deterministic selection of leading qualified topic, engagement, comment and delivery signals",
        denominator=f"{len(insights)} evidence-qualified insight(s)",
        limitations=("Public samples can be selected by platform ranking and collector coverage.",),
        data_required=("Campaign-specific audience analytics and controlled test results",),
    )


def analyse_agency_intelligence(raw: Any, *, signals: Any = None, audience: Any = None,
                                content: Any = None, competitors: Any = None,
                                comments: Any = None, brand: Any = None) -> AgencyIntelligence:
    """Build all requested agency metrics from existing engine objects by duck typing.

    Integration example::

        agency = analyse_agency_intelligence(
            payload.raw, signals=sig, audience=payload.audience,
            content=payload.content, competitors=payload.competitors,
            comments=payload.comments, brand=payload.brand,
        )
        renderer_context["agency_intelligence"] = agency.to_dict()
    """
    demographics = demographic_evidence(audience)
    engagement = engagement_metrics(raw)
    interests = interest_evidence(signals, audience)
    quality = audience_quality_proxy(raw, engagement, comments)
    anomaly = fake_follower_anomaly_screen(raw, comments)
    overlap = audience_overlap_metric(signals, competitors)
    lookalikes = lookalike_metric(signals, competitors)
    contacts = public_contacts(raw)
    reach = estimated_reachable_impressions(raw)
    collaborations = brand_collaboration_evidence(raw)
    affinity = brand_affinity_metric(interests, collaborations)
    history = historical_performance_metric(raw, content)
    influence = influence_score_metric(raw, signals, engagement, quality, reach, brand)
    insights = audience_insight_metric(interests, engagement, comments, reach)
    return AgencyIntelligence(
        methodology_version="1.0.0",
        audience_quality=quality,
        demographics=demographics,
        fake_follower_anomaly=anomaly,
        interests=interests,
        engagement=engagement,
        audience_overlap=overlap,
        lookalike_creators=lookalikes,
        contact_details=contacts,
        estimated_reach=reach,
        brand_collaborations=collaborations,
        influence_score=influence,
        audience_insights=insights,
        brand_affinity=affinity,
        historical_performance=history,
    )


__all__ = [
    "AgencyIntelligence", "AgencyMetric", "EvidenceRef", "analyse_agency_intelligence",
    "audience_overlap_metric", "audience_quality_proxy", "brand_affinity_metric",
    "brand_collaboration_evidence", "demographic_evidence", "engagement_metrics",
    "estimated_reachable_impressions", "fake_follower_anomaly_screen",
    "historical_performance_metric", "influence_score_metric", "interest_evidence",
    "lookalike_metric", "public_contacts", "rank_lookalike_creators",
]
