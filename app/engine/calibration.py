"""Offline calibration checks for report differentiation and accuracy contracts.

This is not self-training from unlabelled web pages.  It is a repeatable evaluation
layer: run diverse labelled/curated profiles through the engine, detect copied narrative,
cross-profile leakage, evidence overclaims and identity gaps, then adjust deterministic
logic only when a failing case proves the change is needed.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from itertools import combinations

from app.schemas import ReportPayload


@dataclass
class CalibrationIssue:
    severity: str
    code: str
    subjects: list[str]
    detail: str


@dataclass
class CalibrationResult:
    profiles: int
    checks_run: int = 0
    issues: list[CalibrationIssue] = field(default_factory=list)
    recommendation_similarity: list[dict] = field(default_factory=list)
    output_fingerprints: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(x.severity == "error" for x in self.issues)

    def as_dict(self) -> dict:
        out = asdict(self)
        out["passed"] = self.passed
        return out


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _recommendation_text(report: ReportPayload) -> str:
    return " ".join(f"{x.get('what', '')} {x.get('why', '')}"
                    for x in report.recommendations).lower()


def _narrative(report: ReportPayload) -> str:
    chunks = [report.subject_name, report.audience.one_liner,
              report.overview.positioning if report.overview else ""]
    chunks.extend(x.get("what", "") for x in report.recommendations)
    chunks.extend(x.get("what", "") for x in report.opportunities)
    return " ".join(chunks).lower()


def _fingerprint(report: ReportPayload) -> str:
    # Ignore run IDs and timestamps. If this still matches, two subjects received the
    # same substantive report output.
    material = {
        "subject": report.subject_name,
        "headline": report.headline_stats,
        "archetype": report.audience.archetype,
        "one_liner": report.audience.one_liner,
        "interests": report.audience.interests,
        "platforms": report.platform_matrix,
        "opportunities": report.opportunities,
        "recommendations": report.recommendations,
    }
    blob = json.dumps(material, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def evaluate(reports: list[ReportPayload], *, similarity_limit: float = 0.72) -> CalibrationResult:
    result = CalibrationResult(profiles=len(reports))
    private_dimensions = ("gender", "city_tier", "income", "device")

    for report in reports:
        subject = report.subject_name
        result.output_fingerprints[subject] = _fingerprint(report)
        result.checks_run += 6

        if not report.verification or not report.verification.get("accounts"):
            result.issues.append(CalibrationIssue(
                "error", "missing_verification_ledger", [subject],
                "No account-level identity evidence was attached to the report."))
        if report.verification and report.verification.get("identity_status") == "insufficient":
            result.issues.append(CalibrationIssue(
                "warning", "identity_insufficient", [subject],
                "Only insufficient identity evidence was available; conclusions need review."))

        for dimension in private_dimensions:
            value = getattr(report.audience, dimension)
            status = getattr(value.status, "value", value.status)
            if not report.raw.manual_input and status != "unavailable":
                result.issues.append(CalibrationIssue(
                    "error", "private_metric_overclaim", [subject],
                    f"{dimension} was {status} without supplied first-party analytics."))
        if (report.audience.archetype == "generalist_creator" and
                getattr(report.audience.age.status, "value", report.audience.age.status)
                != "unavailable" and
                not report.raw.manual_input):
            result.issues.append(CalibrationIssue(
                "error", "unsupported_lifestage_model", [subject],
                "A general/out-of-domain creator received a modelled age distribution."))

        if not report.recommendations:
            result.issues.append(CalibrationIssue(
                "error", "missing_recommendations", [subject], "No recommendations were produced."))
        else:
            primary = report.raw.account(report.raw.seed_platform)
            markers = {_norm(subject), _norm(report.raw.seed_handle or ""),
                       _norm(primary.platform if primary else "")}
            specific = sum(any(m and m in _norm(x.get("what", "")) for m in markers)
                           or bool(re.search(r"\d", x.get("what", "")))
                           for x in report.recommendations)
            if specific / len(report.recommendations) < 0.60:
                result.issues.append(CalibrationIssue(
                    "error", "generic_recommendations", [subject],
                    f"Only {specific}/{len(report.recommendations)} recommendations contain "
                    "subject, platform or measured-result specificity."))

        if report.raw.seed_handle and _norm(report.raw.seed_handle) not in _norm(
                report.seed_url + " " + report.subject_handle):
            result.issues.append(CalibrationIssue(
                "error", "seed_identity_lost", [subject],
                "The output subject no longer contains the supplied seed identity."))

    fingerprints: dict[str, list[str]] = {}
    for subject, fingerprint in result.output_fingerprints.items():
        fingerprints.setdefault(fingerprint, []).append(subject)
    for subjects in fingerprints.values():
        if len(subjects) > 1:
            result.issues.append(CalibrationIssue(
                "error", "duplicate_substantive_output", subjects,
                "Different inputs produced an identical substantive report fingerprint."))

    for left, right in combinations(reports, 2):
        result.checks_run += 2
        similarity = round(SequenceMatcher(
            None, _recommendation_text(left), _recommendation_text(right)).ratio(), 3)
        result.recommendation_similarity.append({
            "left": left.subject_name, "right": right.subject_name,
            "similarity": similarity,
        })
        if similarity > similarity_limit:
            result.issues.append(CalibrationIssue(
                "error", "recommendation_copy_risk", [left.subject_name, right.subject_name],
                f"Recommendation narratives are {similarity:.1%} similar; limit is "
                f"{similarity_limit:.0%}."))

        # Search for another corpus subject/handle leaking into recommendations or the
        # executive narrative. Raw citations are excluded because they may legitimately
        # mention comparisons or media appearances.
        for source, target in ((left, right), (right, left)):
            foreign = [target.raw.seed_handle or "", target.subject_name]
            own = {_norm(source.raw.seed_handle or ""), _norm(source.subject_name)}
            leaked = [x for x in foreign if len(_norm(x)) >= 6 and _norm(x) not in own
                      and _norm(x) in _norm(_narrative(source))]
            if leaked:
                result.issues.append(CalibrationIssue(
                    "error", "cross_profile_leakage", [source.subject_name, target.subject_name],
                    f"Foreign identity text appeared in the narrative: {leaked[0]}"))
    return result
