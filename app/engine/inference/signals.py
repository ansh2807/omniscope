"""Signal extraction: RawProfile -> a flat, typed feature set the rules can reason over.

Every signal records *why* it exists so the rule that consumes it can cite evidence in
the finished report. Nothing here guesses about the audience; it only measures the
creator's own observable behaviour.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from app.engine.inference import benchmarks as B
from app.schemas import ContentItem, Evidence, RawProfile

PRICE_RE = re.compile(r"₹\s?([\d,]+)")


@dataclass
class Signals:
    name: str = ""
    handle: str = ""
    seed_url: str = ""

    # reach
    followers: dict[str, int] = field(default_factory=dict)
    total_audience: int = 0
    primary_platform: str = ""
    platform_skew: float = 0.0            # max share held by one platform
    verified: bool = False

    # text corpus
    bio_text: str = ""
    keywords: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    corpus: str = ""

    # topic model
    topic_scores: dict[str, float] = field(default_factory=dict)
    topic_rank: list[tuple[str, float]] = field(default_factory=list)
    topic_hits: dict[str, int] = field(default_factory=dict)
    topic_terms: dict[str, list[str]] = field(default_factory=dict)
    topic_evidence_total: int = 0
    topic_distinct_terms: int = 0
    archetype: str = "generalist_creator"
    archetype_score: float = 0.0
    curriculum_locked: bool = False

    # language & geography
    language: str = "english"             # english | hinglish | hindi
    language_measured: bool = False        # False => inferred from category, not counted
    geo_scope: str = "national"           # city | regional | national | global
    geo_terms: list[str] = field(default_factory=list)

    # content performance
    top_views: int | None = None
    recent_median_views: int | None = None
    sub_to_view: float | None = None
    decay_ratio: float | None = None
    long_form_share: float | None = None
    median_duration: int | None = None
    upload_months: dict[int, int] = field(default_factory=dict)
    recent_window_days: int | None = None
    recent_sample: int = 0
    series_attrition: float | None = None

    # commerce
    price_points: list[float] = field(default_factory=list)
    price_min: float | None = None
    price_max: float | None = None
    product_kinds: list[str] = field(default_factory=list)
    proven_transactions: int | None = None       # legacy name: public rating count, not sales
    rating: float | None = None
    testimonial_themes: list[str] = field(default_factory=list)

    # funnel surfaces
    capture_channels: list[str] = field(default_factory=list)
    has_owned_site: bool = False
    press_signals: list[str] = field(default_factory=list)

    evidence: list[Evidence] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def cite(self, claim: str, url: str | None = None, note: str | None = None) -> Evidence:
        e = Evidence(claim=claim, source_url=url, collected_at=datetime.utcnow(), note=note)
        self.evidence.append(e)
        return e


def _median(xs: list[int]) -> int | None:
    xs = [x for x in xs if x is not None]
    return int(statistics.median(xs)) if xs else None


def _term_hits(corpus: str, term: str) -> int:
    """Count whole tokens/phrases, never substrings inside unrelated words.

    ``cat`` must match "CAT exam" but not "watercolour"; ``ai`` must not match
    "training". Flexible separators keep forms such as B.Com and B-Com equivalent.
    """
    tokens = re.findall(r"[a-z0-9₹%+]+", (term or "").lower())
    if not tokens:
        return 0
    pattern = r"(?<![a-z0-9])" + r"[\s._/\-]+".join(
        re.escape(token) for token in tokens) + r"(?![a-z0-9])"
    return len(re.findall(pattern, corpus.lower()))


def extract(raw: RawProfile) -> Signals:
    s = Signals(seed_url=raw.seed_url, handle=raw.seed_handle or "", name=raw.display_name or "")

    # ---------------------------------------------------------------- reach
    for acc in raw.accounts:
        if acc.raw.get("analysis_eligible") is False:
            continue
        relationship = acc.raw.get("identity_role", "primary")
        if acc.followers and relationship == "primary":
            s.followers[acc.platform] = max(s.followers.get(acc.platform, 0), acc.followers)
        if acc.verified and relationship == "primary":
            s.verified = True
        if acc.bio:
            s.bio_text += " " + acc.bio
        s.keywords += acc.keywords
        s.highlights += acc.highlights
        if acc.platform in ("telegram", "whatsapp"):
            s.capture_channels.append(acc.platform)
        if acc.platform in ("linktree", "superprofile", "topmate"):
            s.capture_channels.append(acc.platform)
        if acc.platform == "website":
            s.has_owned_site = True
        if acc.platform in ("appstore", "playstore"):
            s.capture_channels.append("mobile_app")
        for p in acc.products:
            if p.price_inr:
                s.price_points.append(p.price_inr)
            s.product_kinds.append(p.kind)
        if acc.raw.get("rating_count"):
            s.proven_transactions = max(s.proven_transactions or 0, int(acc.raw["rating_count"]))
        if acc.raw.get("rating"):
            s.rating = float(acc.raw["rating"])
        for t in acc.testimonials:
            s.testimonial_themes.append(t.text)

    s.total_audience = sum(s.followers.values())
    if s.followers:
        s.primary_platform = max(s.followers, key=s.followers.get)
        s.platform_skew = s.followers[s.primary_platform] / max(s.total_audience, 1)

    if s.price_points:
        s.price_min, s.price_max = min(s.price_points), max(s.price_points)

    # -------------------------------------------------------------- corpus
    content = raw.all_content()
    s.titles = [c.title for c in content if c.title]
    s.corpus = " ".join([s.bio_text, " ".join(s.keywords), " ".join(s.highlights),
                         " ".join(s.titles)]).lower()

    # ---------------------------------------------------------- topic model
    for topic, terms in B.TOPIC_LEXICON.items():
        matched = {term.strip(): _term_hits(s.corpus, term) for term in terms}
        matched = {term: count for term, count in matched.items() if count}
        hits = sum(matched.values())
        if hits:
            s.topic_hits[topic] = hits
            s.topic_terms[topic] = sorted(matched)
            s.topic_scores[topic] = float(hits)
    s.topic_evidence_total = sum(s.topic_hits.values())
    s.topic_distinct_terms = len({term for terms in s.topic_terms.values() for term in terms})
    total = sum(s.topic_scores.values()) or 1.0
    s.topic_scores = {k: v / total for k, v in s.topic_scores.items()}
    s.topic_rank = sorted(s.topic_scores.items(), key=lambda kv: -kv[1])

    best, best_score = "generalist_creator", 0.0
    for arch, cfg in B.ARCHETYPES.items():
        score = sum(s.topic_scores.get(t, 0.0) for t in cfg["topics"])
        if score > best_score:
            best, best_score = arch, score
    if (s.topic_evidence_total < 2 or s.topic_distinct_terms < 2 or
            (best != "generalist_creator" and best_score < 0.45)):
        best, best_score = "generalist_creator", 0.0
    s.archetype, s.archetype_score = best, best_score
    s.curriculum_locked = best in ("exam_prep_educator", "admissions_desk") and best_score > 0.30

    # ------------------------------------------------------------ geography
    city_terms = re.findall(
        r"\b(chandigarh|mohali|panchkula|ludhiana|patiala|noida|delhi|mumbai|pune|"
        r"bengaluru|bangalore|hyderabad|kolkata|chennai|lucknow|jaipur|indore|bhopal|patna)\b",
        s.corpus)
    s.geo_terms = [c.title() for c, _ in Counter(city_terms).most_common(6)]
    if city_terms:
        top, n = Counter(city_terms).most_common(1)[0]
        if n >= 6 and n / max(len(city_terms), 1) > 0.5:
            s.geo_scope = "city"
        elif n >= 3:
            s.geo_scope = "regional"
    if any(t in s.corpus for t in ("study abroad", "uk ", "canada", "ireland", "visa")):
        if s.geo_scope == "national":
            s.geo_scope = "global"

    # ------------------------------------------------------------ language
    # Titles are frequently written in English for search even when delivery is not.
    # Measure what we can, then fall back to the category norm and say so.
    hindi_hits = sum(s.corpus.count(m) for m in B.HINDI_MARKERS)
    s.language_measured = hindi_hits >= 3
    if hindi_hits >= 12:
        s.language = "hindi"
    elif hindi_hits >= 3:
        s.language = "hinglish"
    else:
        indian_curriculum = any(t in s.corpus for t in
                                ("cbse", "class 12", "class 11", "cuet", "ncert",
                                 "board exam", "counselling", "merit list"))
        if indian_curriculum and s.geo_scope == "city":
            s.language = "hindi"
        elif indian_curriculum:
            s.language = "hinglish"
        else:
            s.language = "english"

    # --------------------------------------------------- content performance
    yt = [c for c in content if c.platform == "youtube" and c.views is not None]
    if yt:
        s.top_views = max(c.views for c in yt)
        dated = [c for c in yt if c.published_at]
        tagged_latest = [c for c in yt if (
            c.raw.get("sort") == "latest" or
            "latest" in (c.raw.get("sample") or []))]
        # Prefer the collector's explicit latest sample. Popular/all-time rows are useful
        # for extrema but would badly bias a recent median.
        if len(tagged_latest) >= 4:
            recent = tagged_latest[:30]
            s.recent_window_days = None
        elif dated:
            newest = max(c.published_at for c in dated)
            window = [c for c in dated
                      if (newest - c.published_at).days <= 180]
            if len(window) < 6:
                window = sorted(dated, key=lambda c: c.published_at, reverse=True)[:12]
            recent = window[:40]
            s.recent_window_days = 180 if len(window) >= 6 else None
        else:
            recent = yt[:12]
        s.recent_sample = len(recent)
        s.recent_median_views = _median([c.views for c in recent])
        yt_subs = s.followers.get("youtube")
        if yt_subs and s.recent_median_views:
            s.sub_to_view = s.recent_median_views / yt_subs
        # A popular-sorted sample cannot be used as a historical baseline.  Only compare
        # time windows when rows are dated and the collection did not explicitly mix sorts.
        if dated and not tagged_latest and s.recent_median_views:
            historical = [c.views for c in dated if c not in recent]
            old_median = _median(historical)
            if old_median:
                s.decay_ratio = s.recent_median_views / old_median
        for c in dated:
            m = c.published_at.month
            s.upload_months[m] = s.upload_months.get(m, 0) + 1

    durations = [c.duration_seconds for c in content if c.duration_seconds]
    if durations:
        s.median_duration = int(statistics.median(durations))
        s.long_form_share = sum(1 for d in durations if d > 600) / len(durations)

    s.series_attrition = _series_attrition(content)

    # --------------------------------------------------------------- press
    # Press claims must come from a bio or an independently returned search result. Video
    # titles and SEO keywords frequently mention institutions the creator is discussing.
    press_corpus = s.bio_text.lower()
    for term, label in [
        ("tedx", "TEDx speaker"), ("josh talks", "Josh Talks speaker"),
        ("yourstory", "YourStory feature"), ("humans of bombay", "Humans of Bombay feature"),
        ("forbes", "Forbes mention"), ("linkedin top voice", "LinkedIn Top Voice"),
        ("hindustan times", "Hindustan Times coverage"),
    ]:
        if term in press_corpus:
            s.press_signals.append(label)
    for hit in raw.search_hits:
        blob = f"{hit.title} {hit.snippet}".lower()
        for term, label in [("tedx", "TEDx speaker"), ("josh talks", "Josh Talks speaker"),
                            ("podcast", "Podcast appearance")]:
            if term in blob and label not in s.press_signals:
                s.press_signals.append(label)

    s.capture_channels = sorted(set(s.capture_channels))
    return s


def _series_attrition(content: list[ContentItem]) -> float | None:
    """If the creator publishes numbered multi-part series, how badly do viewers drop off?"""
    parts: dict[str, dict[int, int]] = {}
    for c in content:
        if c.views is None:
            continue
        m = re.search(r"\bpart\s*[-–]?\s*(\d{1,2})\b", c.title, re.I)
        if not m:
            continue
        base = re.sub(r"\bpart\s*[-–]?\s*\d{1,2}\b.*", "", c.title, flags=re.I).strip().lower()
        base = re.sub(r"[^a-z0-9 ]", "", base)[:45]
        if len(base) < 8:
            continue
        parts.setdefault(base, {})[int(m.group(1))] = c.views
    ratios = []
    for series in parts.values():
        if len(series) < 3:
            continue
        first, last = series[min(series)], series[max(series)]
        if first:
            ratios.append(1 - last / first)
    return round(statistics.mean(ratios), 3) if ratios else None
