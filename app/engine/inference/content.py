"""Content analysis.

This is the module that produces the observations a human analyst would make by staring
at a channel for an hour: what the best and worst performers have in common, whether the
back catalogue is carrying the channel, which title patterns actually move views, and
when the audience shows up during the year.

Everything here is measured, not modelled. If a claim appears in this module it is
because the arithmetic supports it, and the number that supports it is carried alongside
so the renderer can print it.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from app.schemas import ContentItem

STOP = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with", "your", "you",
    "is", "are", "how", "what", "this", "that", "it", "at", "by", "from", "be", "will",
    "can", "do", "does", "my", "me", "we", "i", "all", "get", "new", "video", "full",
    "part", "ep", "episode", "watch", "must", "best", "top", "vs", "&", "|", "-", "2024",
    "2025", "2026", "2027", "ka", "ki", "ke", "hai", "aur", "se", "ko",
}
TOKEN = re.compile(r"[a-z0-9₹%+]+")


def recurring_title_tokens(titles: list[str], *, min_count: int = 2,
                           limit: int = 8) -> list[str]:
    """Tokens that appear in at least two published titles. One-off words are ignored."""
    counts: Counter[str] = Counter()
    for title in titles:
        toks = {
            word for word in TOKEN.findall((title or "").lower())
            if word not in STOP and len(word) > 3 and not word.isdigit()
        }
        counts.update(toks)
    return [word for word, n in counts.most_common(limit) if n >= min_count]


@dataclass
class Performer:
    title: str
    views: int
    url: str | None
    platform: str
    published_relative: str | None = None
    duration_seconds: int | None = None
    age_days: int | None = None


@dataclass
class Pattern:
    phrase: str
    n: int                    # how many videos contain it
    median_views: int
    lift: float               # multiple of the channel median
    direction: str            # "works" | "fails"
    basis: str = ""
    confidence: float = 0.0


@dataclass
class ContentAnalysis:
    total_items: int = 0
    measured_items: int = 0
    channel_median: int | None = None       # median of collected, measured sample
    metric_scope: str = ""
    top_performers: list[Performer] = field(default_factory=list)
    worst_performers: list[Performer] = field(default_factory=list)
    winning_patterns: list[Pattern] = field(default_factory=list)   # age-adjusted
    losing_patterns: list[Pattern] = field(default_factory=list)    # age-adjusted
    catalogue_patterns: list[Pattern] = field(default_factory=list) # all-time, raw

    catalogue_median: int | None = None      # dated older comparison sample (legacy name)
    current_median: int | None = None        # explicit latest or dated recent sample
    decay_ratio: float | None = None         # current / older median, never current / top
    current_sample: int = 0
    historical_sample: int = 0
    recency_basis: str = ""
    trend_eligible: bool = False
    top_views: int | None = None
    top_to_median: float | None = None
    sub_to_view: float | None = None

    long_median: int | None = None
    short_median: int | None = None
    format_verdict: str = ""

    cadence_per_month: float | None = None
    active_months: int = 0
    seasonality: dict[str, int] = field(default_factory=dict)
    seasonality_measured: bool = False
    peak_month: str = ""
    trough_month: str = ""

    series: list[dict] = field(default_factory=list)
    series_attrition: float | None = None

    promo_median: int | None = None
    organic_median: int | None = None
    promo_gap: float | None = None

    notes: list[str] = field(default_factory=list)


MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

PROMO_MARKERS = ("admission open", "free form", "100% scholarship", "apply now",
                 "last few seats", "sponsored", "partnered", "use code", "enroll now",
                 "limited seats", "book now", "register now")


def _tokens(title: str) -> list[str]:
    return [t for t in TOKEN.findall(title.lower()) if t not in STOP and len(t) > 1]


def _grams(title: str, n: int) -> list[str]:
    ts = _tokens(title)
    return [" ".join(ts[i:i + n]) for i in range(len(ts) - n + 1)]


def _perf(c: ContentItem, now: datetime) -> Performer:
    age = (now - c.published_at).days if c.published_at else None
    return Performer(title=c.title, views=c.views or 0, url=c.url, platform=c.platform,
                     published_relative=c.published_relative,
                     duration_seconds=c.duration_seconds, age_days=age)


def analyse(items: list[ContentItem], *, subscribers: int | None = None,
            now: datetime | None = None, content_is_exhaustive: bool = False) -> ContentAnalysis:
    now = now or datetime.utcnow()
    ca = ContentAnalysis(total_items=len(items))
    scored = [c for c in items if c.views is not None and c.title]
    ca.measured_items = len(scored)
    ca.metric_scope = (f"{len(scored)} collected items with public view counts; this is a "
                       "sample median, not a full-channel median")
    if len(scored) < 4:
        ca.notes.append(
            "Fewer than four items carried a public view count, so content analysis is "
            "limited. This is normal for Instagram-only subjects."
        )
        return ca

    views = [c.views for c in scored]
    ca.channel_median = int(statistics.median(views))
    ca.top_views = max(views)
    ca.top_to_median = round(ca.top_views / max(ca.channel_median, 1), 2)

    ranked = sorted(scored, key=lambda c: c.views, reverse=True)
    ca.top_performers = [_perf(c, now) for c in ranked[:8]]
    ca.worst_performers = [_perf(c, now) for c in ranked[-5:]][::-1]

    latest = [c for c in scored if _sample_has(c, "latest")]
    popular = [c for c in scored if _sample_has(c, "popular")]
    pattern_items = latest if len(latest) >= 8 else scored
    ca.winning_patterns, ca.losing_patterns = _patterns(pattern_items, ca.channel_median)
    catalogue_items = popular if len(popular) >= 4 else scored
    ca.catalogue_patterns = _catalogue_patterns(
        catalogue_items, int(statistics.median(c.views for c in catalogue_items)))
    _recency(ca, scored, subscribers, now)
    fixed_age = [c for c in scored if _fixed_age_views(c)]
    ca.trend_eligible = bool(content_is_exhaustive and len(fixed_age) >= 8)
    if content_is_exhaustive and not ca.trend_eligible:
        ca.notes.append(
            "Even an exhaustive catalogue cannot establish a growth trend from current lifetime "
            "view totals: older uploads have had longer to accumulate views. The engine requires "
            "equal-age view snapshots (for example, every item at day 30).")
    _format(ca, scored)
    _cadence(ca, latest if len(latest) >= 4 else scored,
             contiguous_latest=len(latest) >= 4,
             content_is_exhaustive=content_is_exhaustive)
    _series(ca, scored)
    _promo(ca, scored)
    return ca


def _sample_has(item: ContentItem, label: str) -> bool:
    sample = item.raw.get("sample") or []
    if isinstance(sample, str):
        sample = [sample]
    return item.raw.get("sort") == label or label in sample


def _fixed_age_views(item: ContentItem) -> bool:
    """True only when `views` is explicitly a fixed-age snapshot, not a lifetime total."""
    return (item.raw.get("views_metric_scope") == "fixed_age"
            and isinstance(item.raw.get("views_age_days"), (int, float))
            and item.raw.get("views_age_days") >= 0)


# --------------------------------------------------------------- title patterns
def _age_matched_index(scored: list[ContentItem]) -> dict[int, float]:
    """Views relative to nearby publication dates.

    A rolling matched baseline avoids the old tertile bug where many unrelated phrases
    received the exact same 'lift'.  Undated rows are excluded: accumulated views cannot
    be age-normalised without a publication date.
    """
    dated = [c for c in scored if c.published_at and c.views is not None]
    if len(dated) < 8:
        return {}
    out: dict[int, float] = {}
    neighbours_n = min(10, max(5, len(dated) // 3))
    for item in dated:
        neighbours = sorted(
            (other for other in dated if other is not item),
            key=lambda other: abs((other.published_at - item.published_at).days),
        )[:neighbours_n]
        baseline = statistics.median(c.views for c in neighbours) if neighbours else 0
        if baseline:
            out[id(item)] = item.views / baseline
    return out


def _patterns(scored: list[ContentItem], median: int) -> tuple[list[Pattern], list[Pattern]]:
    """Which phrases actually move views, once video age is controlled for?

    For every 1-, 2- and 3-gram appearing in at least `min_n` titles, compare the median
    age-normalised percentile of the videos containing it against the 0.5 baseline. A
    phrase scoring 0.80 means videos carrying it typically land in the top fifth of their
    own publishing cohort. Raw median views are carried alongside so the report can quote
    a real number rather than an index.
    """
    matched = _age_matched_index(scored)
    if not matched:
        return [], []
    bucket: dict[str, list[ContentItem]] = defaultdict(list)
    for c in scored:
        seen = set()
        for n in (1, 2, 3):
            for g in _grams(c.title, n):
                if g in seen:
                    continue
                seen.add(g)
                bucket[g].append(c)

    min_n = 4 if len(scored) >= 24 else 3
    cand: list[Pattern] = []
    signatures: dict[str, frozenset[int]] = {}
    for phrase, items in bucket.items():
        usable = [c for c in items if id(c) in matched]
        if len(usable) < min_n or len(items) > len(scored) * 0.60:
            continue
        lift = statistics.median(matched[id(c)] for c in usable)
        if 0.72 < lift < 1.35:
            continue
        med = int(statistics.median(c.views for c in usable))
        confidence = min(0.82, 0.38 + 0.07 * len(usable))
        signatures[phrase] = frozenset(id(c) for c in usable)
        cand.append(Pattern(
            phrase=phrase, n=len(usable), median_views=med,
            lift=round(lift, 2), direction="works" if lift >= 1.35 else "fails",
            basis="median views versus nearest-date items; association, not causation",
            confidence=round(confidence, 2)))

    def dedupe(ps: list[Pattern], reverse: bool) -> list[Pattern]:
        if reverse:
            ps = sorted(ps, key=lambda p: (p.lift, p.phrase.count(" ") + 1, p.n),
                        reverse=True)
        else:
            ps = sorted(ps, key=lambda p: (p.lift, -(p.phrase.count(" ") + 1), -p.n))
        kept: list[Pattern] = []
        for p in ps:
            if any(p.phrase in k.phrase or k.phrase in p.phrase for k in kept):
                continue
            # Suppress different words that merely label the same series and therefore
            # classify almost exactly the same uploads. Reporting "national" and "income"
            # as two independent findings would exaggerate the evidence.
            pset = signatures.get(p.phrase, frozenset())
            if any((len(pset & signatures.get(k.phrase, frozenset())) /
                    max(len(pset | signatures.get(k.phrase, frozenset())), 1)) >= .80
                   for k in kept):
                continue
            kept.append(p)
            if len(kept) >= 6:
                break
        return kept

    wins = dedupe([p for p in cand if p.direction == "works"], reverse=True)
    fails = dedupe([p for p in cand if p.direction == "fails"], reverse=False)
    return wins, fails


def _catalogue_patterns(scored: list[ContentItem], median: int) -> list[Pattern]:
    """All-time raw lift, deliberately *not* age-adjusted.

    This answers a different question from `_patterns`: not "what works now" but "what
    are the biggest things this channel ever did, and what did they have in common".
    Old videos dominate here by construction, which is why the renderer labels this
    section as historical rather than current.
    """
    if not median:
        return []
    bucket: dict[str, list[int]] = defaultdict(list)
    for c in scored:
        seen = set()
        for n in (1, 2, 3):
            for g in _grams(c.title, n):
                if g in seen:
                    continue
                seen.add(g)
                bucket[g].append(c.views)

    min_n = 3 if len(scored) >= 15 else 2
    cand = []
    for phrase, vs in bucket.items():
        if len(vs) < min_n or len(vs) == len(scored):
            continue
        med = int(statistics.median(vs))
        lift = med / median
        if lift < 2.0:
            continue
        cand.append(Pattern(phrase=phrase, n=len(vs), median_views=med,
                            lift=round(lift, 1), direction="works",
                            basis="raw lift within the collected historical/popular sample",
                            confidence=min(0.78, round(0.35 + 0.07 * len(vs), 2))))

    cand.sort(key=lambda p: (p.lift * (1 + 0.30 * p.phrase.count(" ")), p.n), reverse=True)
    kept: list[Pattern] = []
    for p in cand:
        if any(p.phrase in k.phrase or k.phrase in p.phrase for k in kept):
            continue
        kept.append(p)
        if len(kept) >= 5:
            break
    return kept


# ------------------------------------------------------------------- recency
def _recency(ca: ContentAnalysis, scored: list[ContentItem],
             subs: int | None, now: datetime) -> None:
    explicit_latest = [c for c in scored if _sample_has(c, "latest")]
    explicit_popular = [c for c in scored if _sample_has(c, "popular")]
    if len(explicit_latest) >= 4:
        current = explicit_latest[:30]
        ca.current_median = int(statistics.median(c.views for c in current))
        ca.current_sample = len(current)
        ca.recency_basis = (f"median of {len(current)} explicitly latest-sorted items from "
                            "the collector")
        if explicit_popular:
            ca.notes.append(
                "Popular-sorted rows are used for historical outliers only. The engine does not "
                "compare their median with latest uploads because that selection is biased.")
        if subs and ca.current_median:
            ca.sub_to_view = round(ca.current_median / subs, 5)
        return

    dated = [c for c in scored if c.published_at]
    if len(dated) >= 6:
        dated.sort(key=lambda c: c.published_at, reverse=True)
        newest = dated[0].published_at
        current = [c for c in dated if (newest - c.published_at).days <= 180]
        if len(current) < 4:
            current = dated[:max(4, len(dated) // 3)]
        older = [c for c in dated if c not in current]
        ca.current_median = int(statistics.median([c.views for c in current]))
        ca.current_sample = len(current)
        ca.recency_basis = (f"{len(current)} dated items within 180 days of the newest "
                            "collected item; collection completeness is unknown")
        if older:
            ca.catalogue_median = int(statistics.median([c.views for c in older]))
            ca.historical_sample = len(older)
            if len(current) >= 4 and len(older) >= 4 and ca.catalogue_median:
                ca.decay_ratio = round(ca.current_median / ca.catalogue_median, 4)
    else:
        ca.notes.append("Publish dates and an explicit latest sample were unavailable, so "
                        "The engine does not fabricate a current-versus-historical comparison.")
    if subs and ca.current_median:
        ca.sub_to_view = round(ca.current_median / subs, 5)


# -------------------------------------------------------------------- format
def _format(ca: ContentAnalysis, scored: list[ContentItem]) -> None:
    withdur = [c for c in scored if c.duration_seconds]
    if len(withdur) < 6:
        return
    longs = [c.views for c in withdur if c.duration_seconds > 600]
    shorts = [c.views for c in withdur if c.duration_seconds <= 600]
    if not longs or not shorts:
        only = "long-form" if longs else "short-form"
        med = int(statistics.median(longs or shorts))
        ca.format_verdict = (
            f"This channel publishes {only} almost exclusively — {len(withdur)} measured "
            f"items, median {med:,} views. There is no internal comparison to make, which "
            f"is itself a finding: the other format is untested.")
        return
    ca.long_median = int(statistics.median(longs))
    ca.short_median = int(statistics.median(shorts))
    ratio = ca.long_median / max(ca.short_median, 1)
    if ratio >= 1.6:
        ca.format_verdict = (
            f"Long-form has the higher sample median. Videos over ten minutes carry "
            f"{ca.long_median:,} views against {ca.short_median:,} for shorter ones — "
            f"{ratio:.1f}× within this collected sample. This is descriptive; topic and age "
            f"were not held constant.")
    elif ratio <= 0.6:
        ca.format_verdict = (
            f"Short-form has the higher sample median. Videos of ten minutes or less carry "
            f"a median of "
            f"{ca.short_median:,} views against {ca.long_median:,} for longer ones. "
            f"Within this sample long-form is associated with lower views; topic and age "
            f"were not held constant.")
    else:
        ca.format_verdict = (
            f"No large length-group difference appears in this sample: "
            f"{ca.long_median:,} median views for long-form against {ca.short_median:,} for "
            f"short-form. No cause can be assigned.")


# ------------------------------------------------------------------- cadence
def _cadence(ca: ContentAnalysis, scored: list[ContentItem], *, contiguous_latest: bool,
             content_is_exhaustive: bool) -> None:
    dated = [c for c in scored if c.published_at]
    if len(dated) < 6:
        return
    if not contiguous_latest and not content_is_exhaustive:
        ca.notes.append("Cadence was not calculated because the collection is a mixed sample, "
                        "not a consecutive upload history.")
        return
    span_days = (max(c.published_at for c in dated)
                 - min(c.published_at for c in dated)).days or 1
    ca.cadence_per_month = round(len(dated) / (span_days / 30.44), 1)

    fixed_dated = [c for c in dated if _fixed_age_views(c)]
    weighted: dict[int, list[int]] = defaultdict(list)
    for c in fixed_dated:
        weighted[c.published_at.month].append(c.views)
    ca.active_months = len({c.published_at.month for c in dated})
    span_days = (max(c.published_at for c in dated) - min(c.published_at for c in dated)).days
    min_month_count = min((len(v) for v in weighted.values()), default=0)
    fixed_ages = {c.raw.get("views_age_days") for c in fixed_dated}
    if (content_is_exhaustive and len(weighted) >= 10 and span_days >= 330
            and min_month_count >= 2 and len(fixed_ages) == 1):
        med = {m: statistics.median(v) for m, v in weighted.items()}
        peak = max(med.values()) or 1
        ca.seasonality = {MONTHS[m - 1]: int(round(med.get(m, 0) / peak * 100))
                          for m in range(1, 13)}
        ca.seasonality_measured = True
        ca.peak_month = MONTHS[max(med, key=med.get) - 1]
        ca.trough_month = MONTHS[min(med, key=med.get) - 1]


# -------------------------------------------------------------------- series
def _series(ca: ContentAnalysis, scored: list[ContentItem]) -> None:
    groups: dict[str, dict[int, ContentItem]] = defaultdict(dict)
    for c in scored:
        m = re.search(r"\bpart\s*[-–]?\s*(\d{1,2})\b", c.title, re.I)
        if not m:
            continue
        base = re.sub(r"\bpart\s*[-–]?\s*\d{1,2}\b.*", "", c.title, flags=re.I).strip()
        base = re.sub(r"[^A-Za-z0-9 ]", "", base).strip()[:48]
        if len(base) < 8:
            continue
        groups[base][int(m.group(1))] = c

    ratios = []
    for base, parts in groups.items():
        if len(parts) < 3:
            continue
        first, last = parts[min(parts)], parts[max(parts)]
        if not first.views:
            continue
        drop = 1 - (last.views / first.views)
        ratios.append(drop)
        ca.series.append({
            "name": base, "parts": len(parts),
            "first_views": first.views, "last_views": last.views,
            "attrition": round(drop * 100),
            "sequence": [{"part": k, "views": parts[k].views} for k in sorted(parts)],
        })
    if ratios:
        ca.series_attrition = round(statistics.mean(ratios), 3)
    ca.series.sort(key=lambda s: -s["parts"])


# --------------------------------------------------------------- promo vs organic
def _promo(ca: ContentAnalysis, scored: list[ContentItem]) -> None:
    promo = [c.views for c in scored
             if any(m in c.title.lower() for m in PROMO_MARKERS)]
    organic = [c.views for c in scored
               if not any(m in c.title.lower() for m in PROMO_MARKERS)]
    if len(promo) < 3 or len(organic) < 5:
        return
    ca.promo_median = int(statistics.median(promo))
    ca.organic_median = int(statistics.median(organic))
    if ca.organic_median:
        ca.promo_gap = round(1 - ca.promo_median / ca.organic_median, 3)


# ---------------------------------------------------------------- testimonials
THEME_LEXICON: dict[str, tuple[str, list[str]]] = {
    "clarity": ("Clarity and decision resolution",
                ["clarity", "clear", "confusion", "confused", "roadmap", "direction",
                 "structured", "focused"]),
    "confidence": ("Confidence and reassurance",
                   ["confidence", "confident", "roadblock", "doubt", "fear", "motivat",
                    "believe", "patience", "patient"]),
    "personalisation": ("Personalisation",
                        ["personalis", "personaliz", "customis", "customiz", "tailored",
                         "my profile", "specific to"]),
    "approachability": ("Approachability",
                        ["easy to speak", "friendly", "approachable", "comfortable",
                         "listened", "kind"]),
    "expertise": ("Subject expertise",
                  ["knows exactly", "knowledge", "expert", "insightful", "in depth",
                   "detailed"]),
    "outcome": ("Concrete outcome",
                ["converted", "got in", "selected", "cracked", "admit", "placed",
                 "result", "score"]),
}


def testimonial_themes(texts: list[str]) -> list[dict]:
    """Cluster verbatim reviews into recurring themes, with the phrase that matched."""
    if not texts:
        return []
    out = []
    for key, (label, terms) in THEME_LEXICON.items():
        hits, quote = 0, None
        for t in texts:
            low = t.lower()
            if any(term in low for term in terms):
                hits += 1
                if quote is None or len(t) < len(quote):
                    quote = t
        if hits:
            out.append({
                "theme": label, "count": hits, "key": key,
                "share": round(hits / len(texts) * 100),
                "quote": (quote or "")[:220],
            })
    out.sort(key=lambda d: -d["count"])
    for i, d in enumerate(out):
        d["frequency"] = "Dominant" if i == 0 and d["share"] >= 40 else (
            "High" if d["share"] >= 30 else "Medium" if d["share"] >= 15 else "Present")
    return out
