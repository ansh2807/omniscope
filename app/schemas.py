"""Canonical data model.

Two layers:
  * Collection layer  -> RawProfile / PlatformAccount / ContentItem  (facts we observed)
  * Inference layer   -> AudienceModel / Persona / ReportPayload     (what we concluded)

Everything that leaves the collection layer carries a `provenance` so the renderer can
label it OBSERVED, and everything that leaves the inference layer carries a confidence
score plus the evidence that produced it.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ----------------------------------------------------------------- provenance
class Confidence(str, Enum):
    OBSERVED = "observed"        # read from a live public page / dated source
    ESTIMATED = "estimated"      # inferred, always accompanied by a score
    UNAVAILABLE = "unavailable"  # publicly inaccessible; not modelled, not guessed


class ClaimStatus(str, Enum):
    """How a report value was produced.

    ``calculated`` is reserved for arithmetic over observed inputs.  ``modelled`` is a
    directional hypothesis, never a substitute for private first-party analytics.
    """
    OBSERVED = "observed"
    CALCULATED = "calculated"
    MODELLED = "modelled"
    UNAVAILABLE = "unavailable"


class Evidence(BaseModel):
    claim: str
    source_url: str | None = None
    collected_at: datetime | None = None
    note: str | None = None


class Estimate(BaseModel):
    """A single inferred number or band, with its full audit trail."""
    key: str
    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    evidence: list[Evidence] = Field(default_factory=list)
    status: ClaimStatus = ClaimStatus.MODELLED
    method: str = ""

    @property
    def confidence_pct(self) -> int:
        return round(self.confidence * 100)


class Distribution(BaseModel):
    """A normalised categorical distribution plus the confidence in its shape."""
    buckets: dict[str, float]
    confidence: float = 0.5
    reasoning: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    status: ClaimStatus = ClaimStatus.MODELLED
    method: str = ""
    sample_size: int | None = None

    def normalised(self) -> dict[str, float]:
        total = sum(self.buckets.values()) or 1.0
        return {k: v / total for k, v in self.buckets.items()}

    def as_pct(self) -> dict[str, int]:
        n = self.normalised()
        raw = {k: v * 100 for k, v in n.items()}
        out = {k: int(round(v)) for k, v in raw.items()}
        drift = 100 - sum(out.values())
        if drift and out:
            top = max(out, key=out.get)
            out[top] += drift
        return out

    @property
    def modal(self) -> str:
        return max(self.buckets, key=self.buckets.get) if self.buckets else ""


# ----------------------------------------------------------------- collection
Platform = Literal[
    "instagram", "youtube", "linkedin", "x", "threads", "facebook",
    "tiktok", "reddit", "bluesky", "mastodon", "github", "soundcloud", "pinterest", "hackernews", "telegram", "whatsapp", "website", "topmate",
    "superprofile", "linktree", "appstore", "playstore", "podcast", "other",
]


class ContentItem(BaseModel):
    platform: Platform
    title: str = ""
    url: str | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    duration_seconds: int | None = None
    published_at: datetime | None = None
    published_relative: str | None = None
    kind: str = "video"          # video | short | post | reel | carousel | live
    raw: dict[str, Any] = Field(default_factory=dict)


class Product(BaseModel):
    name: str
    price_inr: float | None = None
    compare_at_inr: float | None = None
    kind: str = "service"        # service | course | book | app | membership | package
    url: str | None = None
    rating: float | None = None
    rating_count: int | None = None


class Testimonial(BaseModel):
    text: str
    author: str | None = None
    rating: float | None = None
    dated: str | None = None


class PlatformAccount(BaseModel):
    platform: Platform
    handle: str | None = None
    url: str
    display_name: str | None = None
    bio: str | None = None
    followers: int | None = None
    following: int | None = None
    posts: int | None = None
    verified: bool | None = None
    keywords: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    external_links: list[str] = Field(default_factory=list)
    content: list[ContentItem] = Field(default_factory=list)
    products: list[Product] = Field(default_factory=list)
    testimonials: list[Testimonial] = Field(default_factory=list)
    provenance: Confidence = Confidence.OBSERVED
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    errors: list[str] = Field(default_factory=list)
    needs_manual: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class SearchHit(BaseModel):
    query: str
    title: str
    url: str
    snippet: str = ""
    provider: str = ""
    providers: list[str] = Field(default_factory=list)
    rank: int | None = None
    query_id: str = ""
    purpose: str = ""
    matched_queries: list[str] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)
    identity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    collected_at: datetime = Field(default_factory=datetime.utcnow)


class RawProfile(BaseModel):
    """Everything the collection layer found, before any inference."""
    seed_url: str
    seed_platform: Platform
    seed_handle: str | None = None
    display_name: str | None = None
    accounts: list[PlatformAccount] = Field(default_factory=list)
    search_hits: list[SearchHit] = Field(default_factory=list)
    discovered_urls: list[str] = Field(default_factory=list)
    manual_input: dict[str, Any] = Field(default_factory=dict)
    keyless: dict[str, Any] = Field(default_factory=dict)   # KeylessFindings, serialised
    rejected: list[dict[str, str]] = Field(default_factory=list)  # surfaces considered and dropped
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    warnings: list[str] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)

    def account(self, platform: str) -> PlatformAccount | None:
        for a in self.accounts:
            if a.platform == platform:
                return a
        return None

    def all_content(self) -> list[ContentItem]:
        out: list[ContentItem] = []
        for a in self.accounts:
            if a.raw.get("analysis_eligible") is False:
                continue
            out.extend(a.content)
        return out


# ------------------------------------------------------------------ inference
class Persona(BaseModel):
    name: str
    tag: str
    goal: str
    pain: str
    watches: str
    buys: str
    also_on: str
    reach_with: str
    basis: str = "Content-need hypothesis"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class AudienceModel(BaseModel):
    one_liner: str = ""
    archetype: str = ""
    archetype_label: str = ""

    age: Distribution
    gender: Distribution
    city_tier: Distribution
    income: Distribution
    device: Distribution               # android / ios / desktop / tablet
    format_mix: Distribution
    temperature: Distribution          # cold / warm / hot
    occupation: Distribution | None = None
    education_mix: Distribution | None = None
    career_mix: Distribution | None = None
    sophistication: Distribution | None = None
    consumption: Distribution | None = None
    seasonality: dict[str, int] = Field(default_factory=dict)
    states: Estimate | None = None
    english_proficiency: Estimate | None = None
    regional_language: Estimate | None = None

    country_split: list[Estimate] = Field(default_factory=list)
    top_cities: Estimate | None = None
    education: Estimate | None = None
    career_stage: Estimate | None = None
    language: Estimate | None = None

    interests: list[dict[str, Any]] = Field(default_factory=list)
    psychographics: dict[str, str] = Field(default_factory=dict)
    vocabulary: list[str] = Field(default_factory=list)
    behaviours: list[dict[str, str]] = Field(default_factory=list)
    personas: list[Persona] = Field(default_factory=list)
    activation: list[dict[str, str]] = Field(default_factory=list)
    callouts: list[dict[str, str]] = Field(default_factory=list)
    unavailable: list[dict[str, str]] = Field(default_factory=list)

    overall_confidence: float = 0.5
    signals_fired: list[str] = Field(default_factory=list)


class CreatorOverview(BaseModel):
    """Section 2 — who this person is, from their own published surfaces."""
    positioning: str = ""
    credentials: list[str] = Field(default_factory=list)
    content_pillars: list[str] = Field(default_factory=list)
    product_stack: list[str] = Field(default_factory=list)
    format_range: str = ""
    press: list[str] = Field(default_factory=list)
    verified: bool = False
    base_location: str = ""
    portrait_url: str = ""
    portrait_source: str = ""


class ReportPayload(BaseModel):
    report_id: str
    generated_at: datetime
    subject_name: str
    subject_handle: str
    seed_url: str
    headline_stats: list[dict[str, str]] = Field(default_factory=list)
    raw: RawProfile
    audience: AudienceModel
    overview: CreatorOverview | None = None
    content: Any | None = None        # ContentAnalysis
    funnel: Any | None = None         # FunnelAssessment
    seo: Any | None = None            # SeoAssessment
    competitors: Any | None = None    # CompetitorSet
    comments: Any | None = None       # CommentAnalysis
    brand: Any | None = None          # BrandAnalysis
    growth: Any | None = None         # GrowthAnalysis
    agency: Any | None = None         # AgencyIntelligence decision layer
    media_buy: Any | None = None      # prioritize/pilot/hold/pass scorecard
    diagnostics: Any | None = None    # ResearchDiagnostics
    verification: Any | None = None   # cross-source identity and claim audit
    platforms: list[Any] = Field(default_factory=list)   # PlatformProfile
    platform_matrix: list[dict[str, Any]] = Field(default_factory=list)
    opportunities: list[dict[str, str]] = Field(default_factory=list)
    recommendations: list[dict[str, str]] = Field(default_factory=list)
    desk: dict[str, Any] | None = None
    sentiment: dict[str, Any] = Field(default_factory=dict)
    sources: list[dict[str, str]] = Field(default_factory=list)
    engine_version: str = "3.6.0"

    model_config = {"arbitrary_types_allowed": True}


class CohortPayload(BaseModel):
    report_id: str
    generated_at: datetime
    title: str
    reports: list[ReportPayload]
    cohort: Any | None = None         # CohortAnalysis
    engine_version: str = "3.6.0"

    model_config = {"arbitrary_types_allowed": True}
