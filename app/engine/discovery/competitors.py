"""Competitor discovery.

Finds creators publishing on related topics, then collects enough public data on each to
build a scoped comparison rather than a name-drop. Deliberately budget-aware: it runs a
small number of search queries and fetches at most `max_profiles` competitor pages.

Discovery is topic-driven, not name-driven. Related topic/stage signals do not establish
shared followers or competition for the same people.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.engine.discovery.search import search
from app.schemas import PlatformAccount

# Search templates per archetype. {topic} is filled from the subject's own topic vector.
ARCHETYPE_QUERIES: dict[str, list[str]] = {
    "exam_prep_educator": [
        'best {topic} teacher youtube india',
        'top {topic} educators instagram',
        '"{topic}" one shot revision channel',
    ],
    "entrance_mentor": [
        '{topic} mentor instagram india',
        'best {topic} preparation creators',
        '"{topic}" coaching instagram page',
    ],
    "career_finance_creator": [
        '{topic} career creator instagram india',
        'top finance career youtubers india',
        '"{topic}" educator instagram followers',
    ],
    "admissions_desk": [
        '{topic} admission youtube channel',
        '{topic} counselling updates youtube',
    ],
    "skill_educator": [
        '{topic} course creator instagram india',
        'top {topic} educators youtube india',
    ],
    "generalist_creator": [
        '{topic} creator instagram india',
    ],
}

HANDLE_RE = {
    "instagram": re.compile(r"instagram\.com/([A-Za-z0-9._]{2,40})/?"),
    "youtube": re.compile(r"youtube\.com/@([A-Za-z0-9._\-]{2,40})"),
}
BLOCK = re.compile(r"(/p/|/reel|/explore|/tags|/accounts|/hashtag|/playlist|/watch|"
                   r"/results|/channel/UC|/shorts)", re.I)


@dataclass
class Competitor:
    platform: str
    handle: str
    url: str
    display_name: str | None = None
    followers: int | None = None
    bio: str | None = None
    verified: bool | None = None
    found_via: str = ""
    note: str = ""
    # comparative fields, filled by `_compare`
    size_vs_subject: str = ""
    content_overlap: int | None = None      # % lexical topic overlap
    audience_overlap: str = ""
    positioning: str = ""
    strength: str = ""
    weakness: str = ""


@dataclass
class CompetitorSet:
    assessed: bool = False
    reason: str = ""
    queries_run: int = 0
    candidates_found: int = 0
    competitors: list[Competitor] = field(default_factory=list)
    subject_rank: int | None = None
    subject_followers: int | None = None
    verdict: str = ""


def _clean(url: str) -> str:
    return url.split("?")[0].rstrip("/")


def _compare(cs: "CompetitorSet", subject_followers: int | None,
             topics: list[str]) -> None:
    """Fill the comparative columns the brief asks for, from what we actually collected."""
    from app.engine.inference import benchmarks as B

    subject_terms: set[str] = set()
    for t in topics[:4]:
        subject_terms.update(B.TOPIC_LEXICON.get(t, []))

    for c in cs.competitors:
        blob = f"{c.display_name or ''} {c.bio or ''}".lower()

        # content overlap: how much of the subject's topical vocabulary this account uses
        if blob.strip() and subject_terms:
            hits = sum(1 for term in subject_terms if term in blob)
            c.content_overlap = min(100, round(hits / max(len(subject_terms), 1) * 400))
        # size comparison
        if c.followers and subject_followers:
            r = c.followers / subject_followers
            if r >= 3:
                c.size_vs_subject = f"{r:.1f}× larger"
            elif r >= 1.15:
                c.size_vs_subject = f"{r:.1f}× larger"
            elif r >= 0.85:
                c.size_vs_subject = "comparable"
            else:
                c.size_vs_subject = f"{1/r:.1f}× smaller"
        # Topic/stage affinity only. Public profile data cannot establish follower overlap.
        if c.content_overlap is not None:
            if c.content_overlap >= 45:
                c.audience_overlap = "high topic/stage affinity"
            elif c.content_overlap >= 20:
                c.audience_overlap = "moderate topic affinity"
            else:
                c.audience_overlap = "low topic affinity"
        # positioning, strength, weakness from observable facts only
        c.positioning = (c.bio or "")[:120] or "No public positioning statement."
        strengths, weaknesses = [], []
        if c.verified:
            strengths.append("verified account")
        if c.followers and subject_followers and c.followers > subject_followers:
            strengths.append(f"{c.followers:,} followers vs the subject's {subject_followers:,}")
        if c.bio and any(k in blob for k in ("iim", "iit", "cfa", "frm", "ca ", "founder")):
            strengths.append("credential stated in bio")
        if not c.followers:
            weaknesses.append("no public follower count")
        if c.followers and subject_followers and c.followers < subject_followers:
            weaknesses.append(f"smaller audience ({c.followers:,})")
        if not c.bio:
            weaknesses.append("no positioning statement")
        if c.content_overlap is not None and c.content_overlap < 20:
            weaknesses.append("only loosely in this niche")
        c.strength = "; ".join(strengths) or "Nothing distinguishing observed publicly."
        c.weakness = "; ".join(weaknesses) or "No obvious public weakness."


async def discover(*, archetype: str, topics: list[str], self_handles: set[str],
                   subject_followers: int | None, max_profiles: int = 6,
                   max_queries: int = 6) -> CompetitorSet:
    cs = CompetitorSet(subject_followers=subject_followers)
    topic_terms = [t.replace("_", " ") for t in topics[:2]] or ["education"]
    templates = ARCHETYPE_QUERIES.get(archetype, ARCHETYPE_QUERIES["generalist_creator"])

    queries: list[str] = []
    for tmpl in templates:
        for term in topic_terms:
            q = tmpl.format(topic=term)
            if q not in queries:
                queries.append(q)
    queries = queries[:max_queries]

    probe = await search(queries[0], limit=8)
    if not probe:
        cs.reason = ("No search provider configured, so competitor discovery was skipped. "
                     "Set SEARCH_PROVIDER and re-run to populate this section.")
        return cs
    cs.assessed = True

    seen: dict[str, Competitor] = {}
    all_hits = list(probe)
    cs.queries_run = 1
    for q in queries[1:]:
        all_hits.extend(await search(q, limit=8))
        cs.queries_run += 1

    for hit in all_hits:
        if BLOCK.search(hit.url):
            continue
        for platform, rx in HANDLE_RE.items():
            m = rx.search(hit.url)
            if not m:
                continue
            handle = m.group(1)
            if handle.lower() in self_handles:
                continue
            key = f"{platform}:{handle.lower()}"
            if key in seen:
                continue
            url = (f"https://www.instagram.com/{handle}/" if platform == "instagram"
                   else f"https://www.youtube.com/@{handle}")
            seen[key] = Competitor(platform=platform, handle=handle, url=_clean(url),
                                   display_name=re.sub(r"\s*[-|–(].*$", "", hit.title)[:60],
                                   found_via=hit.query)
    cs.candidates_found = len(seen)

    # Collect the most promising candidates. Instagram first — follower counts there are
    # the comparison everyone actually asks for.
    from app.engine.collectors.instagram import collect as ig_collect
    from app.engine.collectors.youtube import collect as yt_collect

    ordered = sorted(seen.values(), key=lambda c: 0 if c.platform == "instagram" else 1)
    for cand in ordered[:max_profiles]:
        try:
            acc: PlatformAccount = (await ig_collect(cand.handle) if cand.platform == "instagram"
                                    else await yt_collect(cand.handle))
        except Exception as exc:  # noqa: BLE001
            cand.note = f"collection failed: {type(exc).__name__}"
            cs.competitors.append(cand)
            continue
        cand.display_name = acc.display_name or cand.display_name
        cand.followers = acc.followers
        cand.bio = (acc.bio or "")[:220] or None
        cand.verified = acc.verified
        if acc.errors and not acc.followers:
            cand.note = acc.errors[0][:120]
        cs.competitors.append(cand)

    _compare(cs, subject_followers, topics)
    cs.competitors.sort(key=lambda c: -(c.followers or 0))
    ranked = [c for c in cs.competitors if c.followers]
    if subject_followers and ranked:
        bigger = sum(1 for c in ranked if c.followers > subject_followers)
        cs.subject_rank = bigger + 1
        biggest = ranked[0]
        if cs.subject_rank == 1:
            cs.verdict = (
                f"The subject is the largest account found in this niche, ahead of "
                f"{biggest.display_name or biggest.handle} at {biggest.followers:,}.")
        else:
            cs.verdict = (
                f"The subject ranks #{cs.subject_rank} of {len(ranked) + 1} accounts found "
                f"in this niche. {biggest.display_name or biggest.handle} leads with "
                f"{biggest.followers:,} followers against the subject's "
                f"{subject_followers:,}.")
    elif not ranked:
        cs.verdict = ("Candidate accounts were found but none served public follower counts, "
                      "so no ranking is possible. Named competitors are listed for manual "
                      "review.")
    return cs
