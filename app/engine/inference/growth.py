"""Growth analysis.

Trajectory, content evolution, audience evolution, brand evolution, bottlenecks and
missed opportunities — all derived from the time-series inside the collected content
rather than from any private analytics.

The honest limit: follower growth needs follower snapshots, while content-view growth needs
equal-age view snapshots. Current lifetime totals cannot be compared across publication dates
because older items have had longer to accumulate views.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from app.engine.inference import benchmarks as B
from app.engine.inference.content import _fixed_age_views


@dataclass
class Era:
    label: str
    start: str
    end: str
    items: int
    median_views: int
    top_topics: list[str] = field(default_factory=list)
    median_duration_min: float | None = None


@dataclass
class GrowthAnalysis:
    measurable: bool = False
    reason: str = ""
    trend: str = ""                 # accelerating | steady | decelerating | seasonal
    trend_note: str = ""
    trajectory: list[dict] = field(default_factory=list)   # timeline points
    eras: list[Era] = field(default_factory=list)
    content_evolution: str = ""
    audience_evolution: str = ""
    brand_evolution: str = ""
    bottlenecks: list[dict] = field(default_factory=list)
    missed: list[dict] = field(default_factory=list)
    future: list[dict] = field(default_factory=list)


def _topics_of(titles: list[str]) -> list[str]:
    blob = " ".join(titles).lower()
    scores = {}
    for topic, terms in B.TOPIC_LEXICON.items():
        hits = sum(blob.count(t) for t in terms)
        if hits:
            scores[topic] = hits
    return [t.replace("_", " ").title()
            for t, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:3]]


def analyse(raw, sig, content, funnel, seo, comments, brand) -> GrowthAnalysis:
    g = GrowthAnalysis()
    dated = [c for c in raw.all_content() if c.views is not None and c.published_at]
    items = [c for c in dated if _fixed_age_views(c)]

    if len(items) < 8 or not (content and content.trend_eligible):
        if content and content.trend_eligible:
            scope = f"Only {len(items)} equal-age view snapshots were available; at least 8 are required."
        elif dated and getattr(raw, "accounts", None) and any(
                a.raw.get("content_is_exhaustive") for a in raw.accounts):
            scope = (f"{len(dated)} dated lifetime-view rows were collected, but older uploads "
                     "have had longer to accumulate views. Exhaustiveness does not remove that bias.")
        else:
            scope = (f"{len(dated)} dated rows came from a latest-plus-popular or otherwise "
                     "incomplete sample; popular rows over-represent historical winners.")
        g.reason = (
            "A valid content-view trajectory requires a consecutive history measured at the "
            "same age after publication. " + scope + " Follower history is also unavailable; "
            "supply equal-age snapshots or a first-party time series before assigning a trend.")
        _qualitative(g, sig, content, funnel, seo, comments, brand)
        return g

    g.measurable = True
    items.sort(key=lambda c: c.published_at)

    # ------------------------------------------------------------- trajectory
    by_q: dict[str, list[int]] = defaultdict(list)
    for c in items:
        q = f"{c.published_at.year}-Q{(c.published_at.month - 1)//3 + 1}"
        by_q[q].append(c.views)
    for q in sorted(by_q):
        vs = by_q[q]
        g.trajectory.append({"period": q, "items": len(vs),
                             "median_views": int(statistics.median(vs))})

    # --------------------------------------------------------------- the eras
    n = len(items)
    third = max(2, n // 3)
    slices = [("Early", items[:third]), ("Middle", items[third:third * 2]),
              ("Current", items[third * 2:])]
    for label, group in slices:
        if not group:
            continue
        durs = [c.duration_seconds for c in group if c.duration_seconds]
        g.eras.append(Era(
            label=label,
            start=min(c.published_at for c in group).strftime("%b %Y"),
            end=max(c.published_at for c in group).strftime("%b %Y"),
            items=len(group),
            median_views=int(statistics.median([c.views for c in group])),
            top_topics=_topics_of([c.title for c in group]),
            median_duration_min=(round(statistics.median(durs) / 60, 1) if durs else None),
        ))

    # ------------------------------------------------------------------ trend
    if len(g.eras) >= 2:
        first, last = g.eras[0], g.eras[-1]
        ratio = last.median_views / max(first.median_views, 1)
        seasonal = bool(content and content.seasonality_measured
                        and max(content.seasonality.values() or [0])
                        - min(content.seasonality.values() or [0]) >= 60)
        if ratio >= 1.35:
            g.trend = "accelerating"
            g.trend_note = (
                f"Median equal-age views per item have risen from {first.median_views:,} in the "
                f"{first.label.lower()} period ({first.start}) to {last.median_views:,} now "
                f"({last.end}) — a {ratio:.1f}× difference within the measured history.")
        elif ratio <= 0.5:
            g.trend = "seasonal" if seasonal else "decelerating"
            g.trend_note = (
                f"Median equal-age views per item have fallen from {first.median_views:,} "
                f"({first.start}) to {last.median_views:,} ({last.end}), "
                f"{ratio*100:.0f}% of the earlier level. "
                + ("The fixed-age history also shows month-level variation. Re-run with the "
                   "next comparable periods before assigning the change to seasonality."
                   if seasonal else
                   "No measured seasonal pattern explains it; cause still cannot be assigned "
                   "from view totals alone."))
        else:
            g.trend = "steady"
            g.trend_note = (
                f"Median equal-age views per item have moved from {first.median_views:,} to "
                f"{last.median_views:,} — broadly flat within the measured history.")

    # ------------------------------------------------------ content evolution
    if len(g.eras) >= 2:
        early_t, late_t = set(g.eras[0].top_topics), set(g.eras[-1].top_topics)
        gained, lost = late_t - early_t, early_t - late_t
        bits = []
        if gained:
            bits.append("moved into " + ", ".join(sorted(gained)))
        if lost:
            bits.append("moved away from " + ", ".join(sorted(lost)))
        if not bits:
            bits.append(f"stayed on the same core subjects ({', '.join(sorted(early_t))}) "
                        f"throughout; the effect on authority or fatigue was not measured")
        dur_note = ""
        if g.eras[0].median_duration_min and g.eras[-1].median_duration_min:
            d0, d1 = g.eras[0].median_duration_min, g.eras[-1].median_duration_min
            if d1 > d0 * 1.4:
                dur_note = (f" Format has lengthened from a median {d0} to {d1} minutes.")
            elif d1 < d0 * 0.7:
                dur_note = (f" Format has shortened from a median {d0} to {d1} minutes; the "
                            f"reason cannot be assigned from public metadata.")
        g.content_evolution = ("The catalogue has " + "; ".join(bits) + "." + dur_note)

    # ----------------------------------------------------- audience evolution
    ev = []
    if sig.curriculum_locked:
        ev.append("the content serves a recurring academic cycle; follower churn and cohort "
                  "replacement were not measured")
    if content and content.sub_to_view is not None:
        ev.append(f"current-sample median views equal {content.sub_to_view*100:.2f}% of the "
                  f"current subscriber count, not unique subscriber reach")
    if len(sig.followers) > 1:
        ev.append(f"{round(sig.platform_skew*100)}% of summed public follows are on "
                  f"{sig.primary_platform}; duplication is unknown")
    g.audience_evolution = (("Current-snapshot observations: " + "; ".join(ev) + ".") if ev else
                            "Audience evolution is unavailable without repeated first-party or "
                            "public snapshots.")

    # -------------------------------------------------------- brand evolution
    be = []
    if brand and brand.proof:
        be.append(f"{len(brand.proof)} public proof/social-proof items are listed, with each "
                  f"item's source limitations stated")
    if funnel and funnel.rungs:
        be.append(f"the current public catalogue has {len(funnel.rungs)} priced rungs "
                  f"topping out at ₹{int(funnel.price_max):,}; sales are unavailable")
    elif funnel:
        be.append("no public price ladder was observed")
    if sig.press_signals:
        be.append("public bios contain speaking/stage claims that require independent source "
                  "verification")
    g.brand_evolution = (("Current public snapshot: " + "; ".join(be) +
                          ". Direction over time is unavailable from one snapshot.") if be else
                         "Brand trajectory could not be characterised from public evidence.")

    _qualitative(g, sig, content, funnel, seo, comments, brand)
    return g


def _qualitative(g, sig, content, funnel, seo, comments, brand) -> None:
    # ------------------------------------------------------------ bottlenecks
    if funnel and not funnel.owned_audience:
        g.bottlenecks.append({
            "bottleneck": "No verified first-party audience list",
            "evidence": "No observed email list, CRM export or equivalent portable contact "
                        "base. Websites and messaging links do not establish list size.",
            "effect": "Retention and direct re-contact capacity cannot be assessed from the "
                      "public evidence."})
    if content and content.sub_to_view is not None and content.sub_to_view < 0.02:
        g.bottlenecks.append({
            "bottleneck": "Low current views-to-subscriber ratio",
            "evidence": f"Current-sample median views equal {content.sub_to_view*100:.2f}% of "
                        "the public subscriber count.",
            "effect": "This describes view-count scale only. Unique reach, subscriber reach and "
                      "whether followers are dormant require first-party analytics."})
    if len(sig.followers) > 1 and sig.platform_skew > 0.85:
        weak = [p for p in sig.followers if p != sig.primary_platform]
        g.bottlenecks.append({
            "bottleneck": f"Smaller public count on {weak[0].title()}",
            "evidence": f"{round(sig.platform_skew*100)}% of summed public follows are on "
                        f"{sig.primary_platform}; cross-platform duplication is unknown.",
            "effect": "Public account reach is concentrated on one platform. Whether the "
                      "smaller surface is a growth opportunity requires its first-party reach "
                      "and audience-overlap data."})
    if seo and seo.assessed and seo.owns_page_one in ("no", "partial"):
        g.bottlenecks.append({
            "bottleneck": "Weak search ownership",
            "evidence": f"Owns page one: {seo.owns_page_one}; collision risk {seo.collision_risk}.",
            "effect": "This may reduce discovery, but search demand, rankings and lost visits "
                      "were not measured."})
    if funnel and funnel.spread and funnel.spread < 3:
        g.bottlenecks.append({
            "bottleneck": "Flat price ladder",
            "evidence": f"Only a {funnel.spread}× spread between cheapest and dearest product.",
            "effect": "The observed catalogue offers little public price separation. Buyer "
                      "preference, conversion and demand for other tiers are unknown."})
    if content and content.series_attrition and content.series_attrition > 0.5:
        g.bottlenecks.append({
            "bottleneck": "Later series parts carry lower public views",
            "evidence": f"{round(content.series_attrition*100)}% lower lifetime views from "
                        f"the first to final sampled part.",
            "effect": "Later parts have lower public view counts in this sample. Unique-viewer "
                      "retention and the cause of the decline are unknown."})

    # -------------------------------------------------------------- missed
    if content and content.catalogue_patterns and content.winning_patterns is not None:
        best = content.catalogue_patterns[0]
        current = {p.phrase for p in content.winning_patterns}
        if best.phrase not in current:
            g.missed.append({
                "missed": f'The "{best.phrase}" pattern is absent from the latest sample',
                "evidence": f"It carries a median {best.median_views:,} views, {best.lift}× the "
                            f"measured historical/popular-sample median. This is a test idea, "
                            f"not proof that the phrase caused performance."})
    if comments and comments.available:
        for b in comments.buckets:
            if b.label == "Content requests" and b.share >= 5:
                g.missed.append({
                    "missed": "Sampled commenters requested additional content",
                    "evidence": f"{b.share}% of comments contain an explicit request. "
                                f"Example: \"{b.examples[0]}\"" if b.examples else ""})
            if b.label == "Buying intent" and b.share >= 5:
                g.missed.append({
                    "missed": "Sampled comments mention price, enrolment or links",
                    "evidence": f"{b.share}% of comments ask about price, enrolment or links "
                                f"unprompted. Whether those comments converted is unknown."})
    if seo and seo.assessed and seo.intent_clusters:
        c0 = seo.intent_clusters[0]
        if "ceded" in c0.get("gap", ""):
            g.missed.append({
                "missed": f"A first-party page for \"{c0['cluster']}\" was not observed",
                "evidence": f"{c0['value']}. This is a content/property gap; search volume "
                            "and rankings were not measured."})
    if funnel and funnel.social_proof.get("ratings", 0) >= 25 and funnel.price_max and \
            funnel.price_max < 15000:
        g.missed.append({
            "missed": "No higher-priced public offer was observed",
            "evidence": f"{funnel.social_proof['ratings']} public ratings are visible and the "
                        f"public offer ceiling is ₹{int(funnel.price_max):,}. Ratings are not "
                        f"treated as paid transaction volume."})

    # -------------------------------------------------------------- future
    top_topic = (sig.topic_rank[0][0].replace("_", " ") if sig.topic_rank else
                 "the leading observed topic")
    plays = [
        (f"Run a tracked offer test around {top_topic}",
         "Content relevance is observed; product demand, buyer identity and willingness to pay "
         "are not. Use a landing page and explicit conversion event."),
        ("Request a first-party audience and reach pack",
         "Unique reach, follower overlap, geography, age, retention and campaign outcomes are "
         "needed before allocating budget."),
        ("Test one content-format change against a comparable control",
         "Historical public view associations do not establish what caused performance."),
    ]
    g.future = [{"play": p, "why": w} for p, w in plays]
