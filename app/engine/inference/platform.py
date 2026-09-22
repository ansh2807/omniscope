"""Per-platform analysis — the brief's "for every platform" table.

Everything here is derived from what was actually collected on that platform: posting
frequency from publish dates, content categories from titles, tone and hooks from title
openers, and CTAs/hashtags from collected metadata. Public ratios are labelled as ratios,
not unique reach, follower quality or community strength. Where a platform yielded no content, the row says so
instead of inventing a score.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from app.engine.inference import benchmarks as B
from app.engine.inference import content as content_mod
from app.engine.inference.signals import _term_hits
from app.schemas import PlatformAccount, RawProfile

HASHTAG = re.compile(r"#(\w{2,40})")
CTA_PATTERNS = {
    "link in bio": ["link in bio", "bio link", "link 👆", "link above"],
    "subscribe / follow": ["subscribe", "follow me", "follow for", "hit the bell",
                           "turn on notifications"],
    "join community": ["join telegram", "join whatsapp", "join the group", "join our",
                       "community link"],
    "book a call": ["book a call", "book now", "1:1", "one on one", "consultation",
                    "dm me", "dm for"],
    "download / free resource": ["download", "free pdf", "free notes", "get the free",
                                 "free resource", "free guide"],
    "buy / enrol": ["enroll", "enrol", "buy now", "register", "admission open",
                    "limited seats", "batch"],
    "comment / engage": ["comment below", "let me know", "tell me in the comments",
                         "share this", "save this"],
}
HOOK_PATTERNS = {
    "Direct question": re.compile(r"^(how|what|why|when|which|should|can|is|are|do|does)\b", re.I),
    "Numbered list": re.compile(r"^\s*\d+\s+", re.I),
    "Negative / warning": re.compile(r"^(don'?t|never|stop|avoid|mistake|warning|beware)\b", re.I),
    "Superlative": re.compile(r"^(best|top|biggest|highest|fastest|only|ultimate)\b", re.I),
    "Curiosity gap": re.compile(r"(secret|nobody tells|truth about|reality of|what they don'?t)", re.I),
    "Outcome promise": re.compile(r"(guarantee|fixed|marks|lakh|lpa|₹|salary|job in|crack)", re.I),
    "Urgency": re.compile(r"(last date|today|deadline|last \d|hurry|closing|final)", re.I),
}
TONE_MARKERS = {
    "Instructional": ["how to", "step by step", "guide", "explained", "tutorial",
                      "complete", "basics", "part"],
    "Authoritative": ["truth", "reality", "must", "should", "never", "always", "rule"],
    "Motivational": ["dream", "believe", "journey", "story", "inspire", "motivat",
                     "struggle", "success"],
    "Urgent / newsy": ["breaking", "update", "announced", "out now", "released",
                       "last date", "notification", "merit list"],
    "Conversational": ["let's", "lets", "my", "i ", "podcast", "chat", "honest", "q&a"],
    "Promotional": ["admission open", "free form", "scholarship", "enroll", "join now",
                    "limited"],
}


@dataclass
class PlatformProfile:
    platform: str
    handle: str | None
    url: str
    followers: int | None
    items_collected: int
    relationship: str = "primary"
    status: str = "analysed"           # analysed | thin | walled | absent
    note: str = ""

    posting_frequency: str = ""
    cadence_per_month: float | None = None
    content_categories: list[dict] = field(default_factory=list)
    tone: list[dict] = field(default_factory=list)
    hooks: list[dict] = field(default_factory=list)
    ctas: list[dict] = field(default_factory=list)
    hashtags: list[dict] = field(default_factory=list)
    visual_style: str = ""
    storytelling: str = ""
    positioning: str = ""

    engagement_quality: str = ""
    engagement_note: str = ""
    follower_quality: str = ""
    follower_note: str = ""
    community_strength: str = ""
    community_note: str = ""
    virality: str = ""
    virality_note: str = ""
    seo_note: str = ""


def _grade(value: float, bands: list[tuple[float, str]]) -> str:
    for threshold, label in bands:
        if value >= threshold:
            return label
    return bands[-1][1]


def analyse(raw: RawProfile, sig, content_analysis) -> list[PlatformProfile]:
    out: list[PlatformProfile] = []
    for acc in raw.accounts:
        if acc.raw.get("analysis_eligible") is False:
            continue
        local = content_mod.analyse(
            acc.content, subscribers=acc.followers,
            content_is_exhaustive=acc.raw.get("content_is_exhaustive") is True)
        out.append(_one(acc, sig, local))
    out.sort(key=lambda p: -(p.followers or 0))
    return out


def _one(acc: PlatformAccount, sig, ca) -> PlatformProfile:
    p = PlatformProfile(platform=acc.platform, handle=acc.handle, url=acc.url,
                        followers=acc.followers, items_collected=len(acc.content),
                        relationship=acc.raw.get("identity_role", "primary"))

    if acc.needs_manual and not acc.content:
        p.status = "walled"
        p.note = ("Post-level data on this platform sits behind a login wall. Public "
                  "header fields are recorded when Instagram prints them; everything "
                  "else requires analyst input.")
    elif not acc.content:
        p.status = "thin"
        p.note = ("This surface was found and recorded, but yielded no public content "
                  "items to analyse.")

    corpus = " ".join([acc.bio or ""] + [c.title for c in acc.content]
                      + acc.highlights + acc.keywords)
    low = corpus.lower()

    # ------------------------------------------------------- posting frequency
    latest = [c for c in acc.content if (
        c.raw.get("sort") == "latest" or
        "latest" in (c.raw.get("sample") or []))]
    dated = [c for c in (latest or acc.content) if c.published_at]
    if len(dated) >= 4 and (latest or acc.raw.get("content_is_exhaustive") is True):
        span = (max(c.published_at for c in dated)
                - min(c.published_at for c in dated)).days or 1
        p.cadence_per_month = round(len(dated) / (span / 30.44), 1)
        per_week = p.cadence_per_month / 4.33
        p.posting_frequency = (
            f"{p.cadence_per_month}/month (~{per_week:.1f}/week) across the consecutive "
            f"latest-item window")
    elif acc.posts:
        p.posting_frequency = f"{acc.posts:,} lifetime items; no dated sample to measure cadence"

    # ---------------------------------------------------- content categories
    cats: Counter = Counter()
    classifiable = [c for c in acc.content if c.title]
    for item in classifiable:
        title = item.title.lower()
        scores = {topic: sum(_term_hits(title, term) for term in terms)
                  for topic, terms in B.TOPIC_LEXICON.items()}
        if any(scores.values()):
            cats[max(scores, key=scores.get)] += 1
    total = len(classifiable) or 1
    p.content_categories = [
        {"category": k.replace("_", " ").title(), "share": round(v / total * 100)}
        for k, v in cats.most_common(7)]

    # ------------------------------------------------------------------ tone
    tones: Counter = Counter()
    for label, terms in TONE_MARKERS.items():
        hits = sum(low.count(t) for t in terms)
        if hits:
            tones[label] = hits
    tt = sum(tones.values()) or 1
    p.tone = [{"tone": k, "share": round(v / tt * 100)} for k, v in tones.most_common(4)]

    # ----------------------------------------------------------------- hooks
    titles = [c.title for c in acc.content if c.title]
    if titles:
        hooks: Counter = Counter()
        for t in titles:
            for label, rx in HOOK_PATTERNS.items():
                if rx.search(t):
                    hooks[label] += 1
        p.hooks = [{"hook": k, "count": v, "share": round(v / len(titles) * 100)}
                   for k, v in hooks.most_common(5)]

    # ------------------------------------------------------------------ CTAs
    for label, terms in CTA_PATTERNS.items():
        hits = sum(low.count(t) for t in terms)
        if hits:
            p.ctas.append({"cta": label, "mentions": hits})
    p.ctas.sort(key=lambda d: -d["mentions"])
    p.ctas = p.ctas[:6]

    # -------------------------------------------------------------- hashtags
    tags = Counter(HASHTAG.findall(corpus))
    p.hashtags = [{"tag": f"#{t}", "count": k} for t, k in tags.most_common(12)]

    # ------------------------------------------------- quality and community
    p.follower_quality, p.follower_note = _follower_quality(acc, p)
    p.engagement_quality, p.engagement_note = _engagement_quality(acc, p, ca)
    p.community_strength, p.community_note = _community(acc, p, ca)
    p.virality, p.virality_note = _virality(acc, p, ca)
    p.visual_style, p.storytelling = _style(acc, p)
    p.positioning = (acc.bio or "").strip()[:220] or "No public positioning statement found."
    p.seo_note = _seo(acc)
    return p


def _follower_quality(acc: PlatformAccount, p: PlatformProfile) -> tuple[str, str]:
    if not acc.followers:
        return "not measurable", "No public follower count is available on this surface."
    detail = f" Public count: {acc.followers:,} followers."
    if acc.following is not None:
        detail += f" The account follows {acc.following:,}."
    return "not measurable", (
        "Audience authenticity/quality requires follower-level or first-party analytics. "
        "A follower-to-following ratio cannot distinguish real, inactive, bought or relevant "
        "followers." + detail)


def _engagement_quality(acc: PlatformAccount, p: PlatformProfile, ca) -> tuple[str, str]:
    if acc.platform == "youtube" and acc.followers and ca and ca.current_median:
        r = ca.current_median / acc.followers
        return "view-count ratio only", (f"A median recent upload has {ca.current_median:,} "
                       f"public views against "
                       f"{acc.followers:,} subscribers — {r*100:.2f}% across "
                       f"{ca.current_sample} sampled latest/recent items. Views are not unique "
                       f"people or subscriber reach, so this is not an engagement-quality grade.")
    likes = acc.raw.get("avg_likes")
    if likes and acc.followers:
        er = likes / acc.followers
        return "like-to-follower ratio only", (
            f"Analyst-supplied average of {likes:,} likes against {acc.followers:,} "
            f"followers is {er*100:.2f}%. This is not reach-normalised engagement, unique "
            "people, audience quality or a platform-wide performance grade.")
    if acc.platform == "instagram":
        return "not measurable", ("Instagram engagement is login-walled. Supply average "
                                  "reel views and likes through the analyst form to grade "
                                  "this properly.")
    return "not measurable", "No engagement signal available on this surface."


def _community(acc: PlatformAccount, p: PlatformProfile, ca) -> tuple[str, str]:
    signals = []
    if acc.testimonials:
        signals.append(f"{len(acc.testimonials)} public verbatim reviews")
    if acc.raw.get("rating_count"):
        signals.append(f"{acc.raw['rating_count']} public ratings")
    if acc.platform in ("telegram", "whatsapp"):
        signals.append("a public messaging-channel route")
    if acc.highlights:
        signals.append(f"{len(acc.highlights)} curated profile highlights")
    if not signals:
        return "not measurable", ("No public community context was collected. Relationship "
                                  "depth and repeat participation require first-party or "
                                  "member-level data.")
    return "not measurable", ("Public context: " + ", ".join(signals) +
                              ". These do not measure community strength, active members or "
                              "relationship depth.")


def _virality(acc: PlatformAccount, p: PlatformProfile, ca) -> tuple[str, str]:
    latest = [c for c in acc.content if c.views and (
        c.raw.get("sort") == "latest" or "latest" in (c.raw.get("sample") or []))]
    rows = latest if len(latest) >= 5 else [c for c in acc.content if c.views]
    views = [c.views for c in rows]
    if len(views) < 5:
        return "not measurable", "Too few measured items to assess outlier behaviour."
    med = statistics.median(views)
    top = max(views)
    mult = top / max(med, 1)
    if mult >= 25:
        return "high historical dispersion", (
            f"The best collected item did {top:,} views against a sample median of "
            f"{med:,.0f} — {mult:.0f}×. This describes historical spread; it does not "
            f"forecast campaign virality.")
    if mult >= 6:
        return "medium historical dispersion", (
            f"Best-to-sample-median multiple is {mult:.0f}×. It measures past dispersion, "
            f"not future delivery.")
    return "low historical dispersion", (
        f"Best-to-sample-median multiple is {mult:.1f}×. The collected rows are relatively "
        f"tight; no prediction of future virality is made.")


def _style(acc: PlatformAccount, p: PlatformProfile) -> tuple[str, str]:
    durations = [c.duration_seconds for c in acc.content if c.duration_seconds]
    if not durations:
        visual = ("Not assessable from metadata alone — thumbnails and imagery were not "
                  "downloaded.")
    else:
        med = statistics.median(durations)
        if med <= 60:
            visual = ("Collected duration metadata is short-form dominant (median under one "
                      "minute). Cuts, framing and on-screen text were not inspected.")
        elif med <= 900:
            visual = (f"Collected duration metadata is mid-length (median {med//60:.0f} "
                      f"minutes). Visual treatment was not inspected.")
        else:
            visual = (f"Collected duration metadata is long-form dominant (median "
                      f"{med//60:.0f} minutes). Visual treatment was not inspected.")
    kinds = Counter(c.kind for c in acc.content)
    story = ""
    if kinds:
        top_kind = kinds.most_common(1)[0][0]
        story = (f"Most collected items are classified as {top_kind}. Narrative structure "
                 "was not measured because transcripts or full post bodies were not collected.")
    return visual, story


def _seo(acc: PlatformAccount) -> str:
    if acc.keywords:
        return (f"{len(acc.keywords)} publisher-declared channel keywords were collected. "
                f"Their ranking or traffic effect was not measured.")
    if acc.platform == "youtube":
        return "No channel keywords were collected; ranking, traffic and opportunity size are unknown."
    if acc.platform == "instagram":
        return ("Instagram discovery depends on the name field, bio keywords and hashtags "
                "rather than declared metadata.")
    return "No structured SEO metadata available for this surface."
