"""Second-order research diagnostics over observed creator data.

The rest of the report describes the creator. This module describes the *shape and limits*
of the evidence: concentration, dispersion, sampling risk, publishing regularity,
content-title construction, offer architecture and branded-search control.  Every
number below is arithmetic over collected inputs; none is a demographic or commercial
outcome estimate.
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.schemas import ClaimStatus, ContentItem, RawProfile


@dataclass
class EvidenceDimension:
    dimension: str
    status: str
    evidence: str
    unlock: str = ""


@dataclass
class TitleFeature:
    feature: str
    items: int
    share: int
    median_views: int | None
    lift: float | None
    definition: str


@dataclass
class ResearchDiagnostics:
    # Research coverage. This is a completeness index, not a creator quality score.
    evidence_score: int = 0
    evidence_counts: dict[str, int] = field(default_factory=dict)
    evidence_dimensions: list[EvidenceDimension] = field(default_factory=list)
    evidence_read: str = ""

    # Cross-platform concentration.
    platform_hhi: float | None = None
    effective_platforms: float | None = None
    platform_concentration: str = "unavailable"
    platform_shares: list[dict] = field(default_factory=list)

    # Topic breadth.
    topic_entropy: float | None = None
    normalised_topic_entropy: float | None = None
    effective_topics: float | None = None
    topic_read: str = ""

    # Content distribution.
    content_scope: str = ""
    content_n: int = 0
    view_p25: int | None = None
    view_median: int | None = None
    view_p75: int | None = None
    view_iqr: int | None = None
    view_mad: int | None = None
    view_gini: float | None = None
    top20_share: int | None = None
    breakout_rate: int | None = None
    breakout_threshold: int | None = None
    volatility_read: str = ""
    lorenz: list[dict] = field(default_factory=list)

    # Publishing system.
    publishing_items: int = 0
    publishing_window_days: int | None = None
    median_gap_days: float | None = None
    p90_gap_days: float | None = None
    burstiness: float | None = None
    publishing_read: str = ""
    upload_gaps: list[dict] = field(default_factory=list)

    # Creative construction and format effects.
    title_features: list[TitleFeature] = field(default_factory=list)
    lexical_diversity: float | None = None
    title_read: str = ""
    format_long_n: int = 0
    format_short_n: int = 0
    format_ratio: float | None = None
    cliffs_delta: float | None = None
    format_effect: str = "unavailable"
    format_read: str = ""

    # Offer architecture and discoverability.
    sku_count: int = 0
    priced_sku_count: int = 0
    log_price_span: float | None = None
    max_adjacent_price_gap: float | None = None
    price_tier_count: int = 0
    route_readiness: int = 0
    route_components: list[dict] = field(default_factory=list)
    offer_read: str = ""
    serp_results: int = 0
    owned_top3: int | None = None
    owned_top10: int | None = None
    first_owned_rank: int | None = None
    reciprocal_rank: float | None = None
    collision_count: int | None = None
    serp_read: str = ""

    # Source independence.
    source_hosts: int = 0
    independent_hosts: int = 0
    source_read: str = ""

    formula_glossary: list[dict] = field(default_factory=list)


TOKEN = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "with",
        "your", "you", "is", "are", "how", "what", "this", "that", "from", "by",
        "video", "new", "full", "part", "episode", "watch", "ka", "ki", "ke", "hai"}
OWNED_NETWORKS = ("instagram.com", "youtube.com", "youtu.be", "linkedin.com", "x.com",
                  "twitter.com", "threads.net", "facebook.com", "t.me", "topmate.io",
                  "superprofile.bio", "linktr.ee", "beacons.ai", "apps.apple.com",
                  "play.google.com")


def _sample_has(item: ContentItem, label: str) -> bool:
    sample = item.raw.get("sample") or []
    if isinstance(sample, str):
        sample = [sample]
    return item.raw.get("sort") == label or label in sample


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return float(xs[lo])
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _gini(values: list[int]) -> float | None:
    xs = sorted(max(0, x) for x in values)
    total = sum(xs)
    if not xs or not total:
        return None
    n = len(xs)
    return (2 * sum((i + 1) * x for i, x in enumerate(xs)) / (n * total)
            - (n + 1) / n)


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def _status(value) -> str:
    status = getattr(value, "status", ClaimStatus.UNAVAILABLE)
    return getattr(status, "value", str(status))


def _evidence(raw, audience, ca, fa, se, cm) -> tuple[list[EvidenceDimension], int, dict]:
    items = raw.all_content()
    products = [p for a in raw.accounts for p in a.products]
    dated = [c for c in items if c.published_at]
    engaged = [c for c in items if c.likes is not None or c.comments is not None]

    dims = [
        EvidenceDimension("Identity and positioning", "observed" if raw.display_name else "unavailable",
                          "Creator name and public bios were collected." if raw.display_name else "No stable public identity metadata was collected.",
                          "Supply a verified creator profile."),
        EvidenceDimension("Cross-platform footprint", "observed" if raw.accounts else "unavailable",
                          f"{len(raw.accounts)} attributed public account(s) collected.",
                          "Supply official profile links."),
        EvidenceDimension("Public following", "observed" if any(a.followers for a in raw.accounts) else "unavailable",
                          f"Public counts available on {sum(bool(a.followers) for a in raw.accounts)} account(s).",
                          "Provide a public account or first-party export."),
        EvidenceDimension("Content corpus", "observed" if items else "unavailable",
                          f"{len(items)} public content item(s) collected.",
                          "Enable the official platform API or supply a content export."),
        EvidenceDimension("Content dates", "observed" if dated else "unavailable",
                          f"{len(dated)} item(s) carry exact publication dates.",
                          "Supply a dated content export."),
        EvidenceDimension("Public view counts", "observed" if ca and ca.measured_items else "unavailable",
                          f"{ca.measured_items if ca else 0} item(s) carry view counts.",
                          "Supply platform analytics or enable YouTube Data API access."),
        EvidenceDimension("Content delivery distribution", "calculated" if ca and ca.measured_items >= 4 else "unavailable",
                          ("Percentiles, dispersion and concentration can be calculated over the collected view sample."
                           if ca and ca.measured_items >= 4 else "Too few measured items for a distribution."),
                          "Collect at least four comparable items; 20 or more is preferable."),
        EvidenceDimension("Publishing-system intervals", "calculated" if len(dated) >= 4 else "unavailable",
                          (f"Consecutive gaps can be calculated from {len(dated)} exact publication dates."
                           if len(dated) >= 4 else "Too few exact publication dates for interval analysis."),
                          "Supply at least four exact, consecutive publication dates."),
        EvidenceDimension("Public engagement counts", "observed" if engaged else "unavailable",
                          f"{len(engaged)} item(s) carry like or comment counts.",
                          "Supply post-level analytics."),
        EvidenceDimension("Audience verbatims", "observed" if cm and cm.available else "unavailable",
                          f"{cm.sample_size if cm else 0} public comment(s) analysed.",
                          "Enable public comment collection or supply a consented export."),
        EvidenceDimension("Comment classifications", "calculated" if cm and cm.available else "unavailable",
                          ("Lexicon classes, confidence intervals and repetition checks calculated over the comment sample."
                           if cm and cm.available else "No audience-text sample was available to classify."),
                          "Collect public comments or supply a consented text export."),
        EvidenceDimension("Offers and public pricing", "observed" if products else "unavailable",
                          f"{len(products)} offer(s), {sum(p.price_inr is not None for p in products)} with public price.",
                          "Supply official offer/storefront URLs."),
        EvidenceDimension("Offer architecture", "calculated" if products else "unavailable",
                          ("Price span, adjacent gaps and routing coverage can be calculated."
                           if products else "No public offer set was available for architecture analysis."),
                          "Supply the current public catalogue and routing map."),
        EvidenceDimension("Branded search results", "calculated" if se and se.assessed else "unavailable",
                          "Ownership calculated over a sampled live results page." if se and se.assessed else "No search-results sample was collected.",
                          "Configure a search provider and rerun."),
        EvidenceDimension("Audience age", _status(audience.age), audience.age.reasoning,
                          "Supply a dated first-party audience analytics export."),
        EvidenceDimension("Audience gender", _status(audience.gender), audience.gender.reasoning,
                          "Supply a dated first-party audience analytics export."),
        EvidenceDimension("Audience geography", _status(audience.city_tier), audience.city_tier.reasoning,
                          "Supply country and city analytics."),
        EvidenceDimension("Audience income and device", "observed" if _status(audience.income) == _status(audience.device) == "observed" else "unavailable",
                          "Both dimensions require first-party or survey evidence.",
                          "Supply device analytics and a consented income survey."),
        EvidenceDimension("Unique reach and audience overlap", "unavailable",
                          "Public follower totals cannot identify unique people or cross-platform duplication.",
                          "Supply matched first-party reach data or a privacy-safe overlap study."),
        EvidenceDimension("Conversion, revenue and retention", "unavailable",
                          "No transaction or CRM evidence is inferred from ratings, comments or prices.",
                          "Supply analytics, checkout and CRM exports for the same dated period."),
        EvidenceDimension("Prior campaign outcomes", "unavailable",
                          "No impression, click, conversion, lift or brand-safety delivery file was supplied.",
                          "Supply a dated campaign wrap report with definitions and denominator data."),
    ]
    counts = {s: sum(d.status == s for d in dims)
              for s in ("observed", "calculated", "modelled", "unavailable")}
    # Completeness only. Calculated evidence is nearly as usable as observed inputs;
    # modelled evidence receives limited credit and unavailable evidence none.
    score = round(100 * (counts["observed"] + .85 * counts["calculated"]
                         + .25 * counts["modelled"]) / len(dims))
    return dims, score, counts


def _content(d: ResearchDiagnostics, raw: RawProfile) -> None:
    scored = [c for c in raw.all_content() if c.views is not None and c.title]
    latest = [c for c in scored if _sample_has(c, "latest")]
    sample = latest if len(latest) >= 8 else scored
    d.content_n = len(sample)
    d.content_scope = ("latest collected window" if sample is latest else
                       "all collected items with public views")
    if len(sample) < 4:
        d.volatility_read = "Fewer than four measured items; distribution diagnostics withheld."
        return
    views = [int(c.views or 0) for c in sample]
    if not sum(views):
        d.volatility_read = "All collected public view counts are zero; distribution diagnostics withheld."
        return
    d.view_p25 = round(_pct(views, .25))
    d.view_median = round(_pct(views, .5))
    d.view_p75 = round(_pct(views, .75))
    d.view_iqr = d.view_p75 - d.view_p25
    d.view_mad = round(statistics.median(abs(x - d.view_median) for x in views))
    g = _gini(views)
    d.view_gini = round(g, 3) if g is not None else None
    top_n = max(1, math.ceil(len(views) * .2))
    d.top20_share = round(sum(sorted(views, reverse=True)[:top_n]) / max(sum(views), 1) * 100)
    d.breakout_threshold = 3 * d.view_median
    d.breakout_rate = round(sum(x >= d.breakout_threshold for x in views) / len(views) * 100)
    label = ("winner-dependent" if (d.view_gini or 0) >= .55 or d.top20_share >= 65 else
             "uneven" if (d.view_gini or 0) >= .35 else "comparatively even")
    d.volatility_read = (
        f"The {d.content_scope} is {label}: its top fifth supplies {d.top20_share}% of "
        f"sampled views and the Gini coefficient is {d.view_gini:.3f}. "
        f"{d.breakout_rate}% of items clear the breakout rule of 3x the sample median."
    )
    xs, total, running = sorted(views), sum(views), 0
    d.lorenz = [{"x": 0, "y": 0}]
    for i, value in enumerate(xs, 1):
        running += value
        d.lorenz.append({"x": round(i / len(xs) * 100, 1),
                         "y": round(running / max(total, 1) * 100, 1)})

    # Publishing intervals use exact dates only and the latest sample when available.
    dated = [c for c in (latest if len(latest) >= 4 else sample) if c.published_at]
    dates = sorted({c.published_at.date() for c in dated})
    if len(dates) >= 4:
        gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
        d.publishing_items = len(dates)
        d.publishing_window_days = (dates[-1] - dates[0]).days
        d.median_gap_days = round(statistics.median(gaps), 1)
        d.p90_gap_days = round(_pct(gaps, .9), 1)
        mean = statistics.mean(gaps)
        sd = statistics.pstdev(gaps)
        d.burstiness = round((sd - mean) / (sd + mean), 3) if sd + mean else 0.0
        d.upload_gaps = [{"label": dates[i].isoformat(), "days": gaps[i - 1]}
                         for i in range(1, len(dates))]
        cadence = ("bursty" if d.burstiness > .2 else
                   "regular" if d.burstiness < -.2 else "mixed")
        d.publishing_read = (
            f"Exact dates produce {len(gaps)} intervals across {d.publishing_window_days} days. "
            f"Median gap is {d.median_gap_days:g} days, the 90th-percentile gap is "
            f"{d.p90_gap_days:g} days, and burstiness is {d.burstiness:.3f} ({cadence})."
        )

    # Transparent title-feature comparisons. These are descriptive, not causal.
    features = [
        ("Question framing", lambda s: "?" in s or bool(re.match(r"\s*(how|why|what|which|can|should)\b", s, re.I)), "Question mark or interrogative opening"),
        ("Numeral or quantified promise", lambda s: bool(re.search(r"\b\d+[\d,.]*\b|%", s)), "Numeral, percentage or numbered list"),
        ("Urgency marker", lambda s: bool(re.search(r"\b(now|today|last|deadline|urgent|must|before|never)\b", s, re.I)), "Time pressure or loss-avoidance marker"),
        ("Outcome marker", lambda s: bool(re.search(r"\b(rank|score|salary|job|admission|selected|pass|crack|result|growth|income)\b", s, re.I)), "Concrete result or transformation word"),
        ("Comparison marker", lambda s: bool(re.search(r"\bvs\.?\b|versus|difference|better|best|which one", s, re.I)), "Explicit choice or comparison language"),
        ("Direct address", lambda s: bool(re.search(r"\b(you|your|aap|tum)\b", s, re.I)), "Second-person address"),
    ]
    for label, fn, definition in features:
        yes = [c for c in sample if fn(c.title)]
        no = [c for c in sample if not fn(c.title)]
        med = round(statistics.median(c.views for c in yes)) if yes else None
        base = statistics.median(c.views for c in no) if no else None
        lift = round(med / base, 2) if med is not None and base else None
        d.title_features.append(TitleFeature(label, len(yes), round(len(yes) / len(sample) * 100),
                                            med, lift, definition))
    toks = [t for c in sample for t in TOKEN.findall(c.title.lower())
            if len(t) > 1 and t not in STOP]
    d.lexical_diversity = round(len(set(toks)) / len(toks), 3) if toks else None
    used = [x for x in d.title_features if x.items >= 3 and x.lift is not None]
    if used:
        strongest = max(used, key=lambda x: x.lift)
        d.title_read = (
            f"{strongest.feature} is the strongest recurring tested construction at "
            f"{strongest.lift}x the median of titles without it across {strongest.items} items. "
            "It is an association over the selected window; topic and distribution can explain it."
        )

    long = [c.views for c in sample if c.kind != "short" and c.views is not None]
    short = [c.views for c in sample if c.kind == "short" and c.views is not None]
    d.format_long_n, d.format_short_n = len(long), len(short)
    if len(long) >= 3 and len(short) >= 3:
        ml, ms = statistics.median(long), statistics.median(short)
        d.format_ratio = round(ml / max(ms, 1), 2)
        delta = sum((x > y) - (x < y) for x in long for y in short) / (len(long) * len(short))
        d.cliffs_delta = round(delta, 3)
        magnitude = ("negligible" if abs(delta) < .147 else "small" if abs(delta) < .33
                     else "medium" if abs(delta) < .474 else "large")
        d.format_effect = magnitude
        winner = "long-form" if delta > 0 else "short-form" if delta < 0 else "neither"
        d.format_read = (
            f"{winner.title()} has the higher sampled distribution. Median long-to-short "
            f"view ratio is {d.format_ratio}x; Cliff's delta is {d.cliffs_delta:.3f} "
            f"({magnitude}). Publication age and topic remain uncontrolled."
        )


def _platform_and_topics(d: ResearchDiagnostics, sig) -> None:
    followers = {k: v for k, v in sig.followers.items() if v and v > 0}
    total = sum(followers.values())
    if total:
        shares = {k: v / total for k, v in followers.items()}
        d.platform_hhi = round(sum(s * s for s in shares.values()), 3)
        d.effective_platforms = round(1 / d.platform_hhi, 2)
        d.platform_concentration = ("very high" if d.platform_hhi >= .5 else
                                    "high" if d.platform_hhi >= .3 else
                                    "moderate" if d.platform_hhi >= .18 else "distributed")
        d.platform_shares = [{"platform": k, "followers": followers[k],
                              "share": round(v * 100, 1)}
                             for k, v in sorted(shares.items(), key=lambda x: -x[1])]

    ranked = [(k, v) for k, v in sig.topic_rank if v > 0]
    if ranked:
        total_t = sum(v for _, v in ranked)
        ps = [v / total_t for _, v in ranked]
        entropy = -sum(p * math.log(p) for p in ps)
        d.topic_entropy = round(entropy, 3)
        d.normalised_topic_entropy = round(entropy / math.log(len(ps)), 3) if len(ps) > 1 else 0.0
        d.effective_topics = round(math.exp(entropy), 2)
        label = ("focused" if (d.normalised_topic_entropy or 0) < .45 else
                 "balanced" if d.normalised_topic_entropy < .75 else "broad")
        d.topic_read = (
            f"The public corpus is {label}: normalised topic entropy is "
            f"{d.normalised_topic_entropy:.3f}, equivalent to {d.effective_topics} equally "
            "represented topics. This measures content breadth, not audience interests."
        )


def _offers_search_sources(d: ResearchDiagnostics, raw: RawProfile, fa, se) -> None:
    products = [p for a in raw.accounts for p in a.products]
    prices = sorted(p.price_inr for p in products if p.price_inr is not None and p.price_inr > 0)
    d.sku_count, d.priced_sku_count = len(products), len(prices)
    if prices:
        d.log_price_span = round(math.log10(max(prices) / min(prices)), 3) if len(prices) > 1 else 0.0
        ratios = [prices[i] / prices[i - 1] for i in range(1, len(prices)) if prices[i - 1]]
        d.max_adjacent_price_gap = round(max(ratios), 2) if ratios else None
        d.price_tier_count = len({r.tier for r in fa.rungs}) if fa else 0
    components = [
        ("Explicit lead magnet", bool(fa and fa.lead_magnets), 15),
        ("Permissioned channel", bool(fa and fa.permissioned_channels), 20),
        ("Owned web property", bool(fa and fa.owned_properties), 15),
        ("Routing surface", bool(fa and fa.routing_surfaces), 10),
        ("Public price ladder", bool(fa and fa.rungs), 15),
        ("Explicit first-party list evidence", bool(fa and fa.owned_audience), 25),
    ]
    d.route_components = [{"component": name, "observed": yes, "weight": weight}
                          for name, yes, weight in components]
    d.route_readiness = sum(weight for _, yes, weight in components if yes)
    d.offer_read = (
        f"{d.priced_sku_count} priced SKU(s) span {d.log_price_span:.3f} log10 units"
        if d.log_price_span is not None else "No public price distribution was available"
    ) + (f"; the largest adjacent step is {d.max_adjacent_price_gap}x. "
         if d.max_adjacent_price_gap else ". ") + (
        f"Routing-evidence coverage is {d.route_readiness}/100. This measures visible "
        "infrastructure, not visits, conversion or revenue."
    )

    name = (raw.display_name or raw.seed_handle or "").strip()
    name_hits = [h for h in raw.search_hits
                 if name and name.split()[0].lower() in h.query.lower()]
    hits = list((name_hits or raw.search_hits)[:10])
    if se and se.assessed and hits:
        owned_hosts = {_host(a.url) for a in raw.accounts}
        owned = [(_host(h.url) in owned_hosts or any(n in _host(h.url) for n in OWNED_NETWORKS))
                 for h in hits]
        d.serp_results = len(hits)
        d.owned_top3 = sum(owned[:3])
        d.owned_top10 = sum(owned)
        d.first_owned_rank = next((i + 1 for i, yes in enumerate(owned) if yes), None)
        d.reciprocal_rank = round(1 / d.first_owned_rank, 3) if d.first_owned_rank else 0.0
        d.collision_count = len(se.competing_entities)
        d.serp_read = (
            f"Creator-controlled or platform properties occupy {d.owned_top3}/3 top results "
            f"and {d.owned_top10}/{len(hits)} sampled results. First owned rank is "
            f"{d.first_owned_rank or 'not present'}, reciprocal rank {d.reciprocal_rank}."
        )

    account_hosts = {_host(a.url) for a in raw.accounts if _host(a.url)}
    search_hosts = {_host(h.url) for h in raw.search_hits if _host(h.url)}
    all_hosts = account_hosts | search_hosts
    independent = {h for h in search_hosts if h not in account_hosts
                   and not any(n in h for n in OWNED_NETWORKS)}
    d.source_hosts, d.independent_hosts = len(all_hosts), len(independent)
    d.source_read = (
        f"The report cites {d.source_hosts} distinct host(s), including "
        f"{d.independent_hosts} independent off-network host(s). Creator-owned and platform "
        "surfaces establish what was published; independent sources are needed to corroborate "
        "external reputation claims."
    )


def analyse(raw: RawProfile, sig, audience, ca, fa, se, cm) -> ResearchDiagnostics:
    d = ResearchDiagnostics()
    dims, score, counts = _evidence(raw, audience, ca, fa, se, cm)
    d.evidence_dimensions, d.evidence_score, d.evidence_counts = dims, score, counts
    d.evidence_read = (
        f"Research completeness is {score}/100 across {len(dims)} decision dimensions: "
        f"{counts['observed']} observed, {counts['calculated']} calculated, "
        f"{counts['modelled']} modelled and {counts['unavailable']} unavailable. "
        "This is a coverage index, not a creator, audience or investment score."
    )
    _platform_and_topics(d, sig)
    _content(d, raw)
    _offers_search_sources(d, raw, fa, se)
    d.formula_glossary = [
        {"metric": "Evidence coverage", "formula": "100 × (O + 0.85C + 0.25M) / dimensions",
         "use": "Research completeness only; unavailable fields score zero."},
        {"metric": "Platform HHI", "formula": "Σ(platform follower share²)",
         "use": "Concentration of summed public account follows; duplicates remain unknown."},
        {"metric": "Effective platforms", "formula": "1 / HHI",
         "use": "Number of equally sized platforms that would create the same concentration."},
        {"metric": "Normalised topic entropy", "formula": "−Σ(p ln p) / ln(k)",
         "use": "Breadth of classified content topics from 0 focused to 1 even."},
        {"metric": "View Gini", "formula": "Relative mean difference over sampled item views",
         "use": "0 is even delivery; values nearer 1 indicate winner dependence."},
        {"metric": "Breakout rate", "formula": "items with views ≥ 3 × sample median / n",
         "use": "Frequency of extreme winners under the engine's explicit rule."},
        {"metric": "Publishing burstiness", "formula": "(σ gap − μ gap) / (σ gap + μ gap)",
         "use": "−1 regular, 0 mixed/Poisson-like, +1 highly bursty."},
        {"metric": "Cliff's delta", "formula": "P(long > short) − P(long < short)",
         "use": "Non-parametric format effect over the sampled views."},
        {"metric": "Price span", "formula": "log10(max public price / min public price)",
         "use": "Offer-ladder breadth, not willingness to pay."},
        {"metric": "Reciprocal rank", "formula": "1 / rank of first owned result",
         "use": "Visibility of the first creator-controlled/platform property."},
    ]
    return d
