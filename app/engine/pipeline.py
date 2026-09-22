"""Orchestration: seed URL -> RawProfile -> Signals -> AudienceModel -> rendered report."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.engine.collectors import bluesky as bsky
from app.engine.collectors import github as gh
from app.engine.collectors import hackernews as hn
from app.engine.collectors import mastodon as masto
from app.engine.collectors import pinterest as pin
from app.engine.collectors import instagram as ig
from app.engine.collectors import linkedin as li
from app.engine.collectors import podcast as pod
from app.engine.collectors import reddit as reddit_col
from app.engine.collectors import soundcloud as sc
from app.engine.collectors import tiktok as tt
from app.engine.collectors import web as webcol
from app.engine.collectors import x as x_col
from app.engine.collectors import youtube as yt
from app.engine.discovery.corroborate import enforce as enforce_identity
from app.engine.discovery.expander import classify as classify_surface
from app.engine.discovery.expander import expand
from app.engine.discovery.keyless import KeylessFindings, gather as gather_keyless
from app.engine.discovery.probe import run as probe_handles
from app.engine.discovery import verify as v
from app.engine import assemble, cohort
from app.engine.discovery.competitors import discover as discover_competitors
from app.engine.inference.signals import extract
from app.engine.resolver import resolve
from app.schemas import CohortPayload, PlatformAccount, RawProfile, ReportPayload

Progress = Callable[[str, int], None]


def _noop(stage: str, pct: int) -> None:  # pragma: no cover
    pass


def _account_key(url: str) -> str:
    """Canonical identity key so www/tracking variants cannot duplicate an account."""
    try:
        p = urlsplit(url)
        # Account pages are path-addressed on supported networks.  The only
        # identity-bearing query we retain is an app-store numeric id.
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if k.lower() == "id"]
        return urlunsplit((p.scheme.lower(), p.netloc.lower().removeprefix("www."),
                           p.path.rstrip("/") or "/", urlencode(query), ""))
    except Exception:
        return url.rstrip("/").lower()


def _add_account(raw: RawProfile, incoming: PlatformAccount) -> PlatformAccount:
    """Append or merge the same canonical surface without losing richer collection data."""
    existing = next((a for a in raw.accounts if _account_key(a.url) ==
                     _account_key(incoming.url)), None)
    if existing is None:
        raw.accounts.append(incoming)
        return incoming

    if len(incoming.display_name or "") > len(existing.display_name or ""):
        existing.display_name = incoming.display_name
    if len(incoming.bio or "") > len(existing.bio or ""):
        existing.bio = incoming.bio
    existing.handle = existing.handle or incoming.handle
    def largest(*values: int | None) -> int | None:
        return max((x for x in values if x is not None), default=0) or None

    existing.followers = largest(existing.followers, incoming.followers)
    existing.following = largest(existing.following, incoming.following)
    existing.posts = largest(existing.posts, incoming.posts)
    existing.verified = bool(existing.verified or incoming.verified) or None
    existing.needs_manual = existing.needs_manual and incoming.needs_manual

    def extend_unique(attr: str, key) -> None:
        target = getattr(existing, attr)
        seen = {key(x) for x in target}
        for item in getattr(incoming, attr):
            marker = key(item)
            if marker not in seen:
                seen.add(marker)
                target.append(item)

    extend_unique("content", lambda x: x.url or
                  (x.platform, x.title.lower(), str(x.published_at or "")))
    extend_unique("products", lambda x: (x.name.lower(), x.price_inr, x.url or ""))
    extend_unique("testimonials", lambda x: (x.text[:160], x.author or ""))
    for attr in ("keywords", "highlights", "external_links", "errors"):
        values = list(dict.fromkeys(getattr(existing, attr) + getattr(incoming, attr)))
        setattr(existing, attr, values)
    protected = {k: existing.raw.get(k) for k in ("verified_via", "identity_role")
                 if existing.raw.get(k)}
    existing.raw.update(incoming.raw)
    existing.raw.update(protected)
    existing.raw["merged_observations"] = existing.raw.get("merged_observations", 1) + 1
    return existing


def _apply_keyless_identity(raw: RawProfile, seed_acc: PlatformAccount | None,
                            kl: KeylessFindings, platform: str, handle: str) -> None:
    """Fold Wikidata/Wikipedia identity into the seed when the page printed nothing."""
    if kl.display_name and (not raw.display_name or raw.display_name.lower() == handle.lower()):
        raw.display_name = kl.display_name
        if seed_acc and (not seed_acc.display_name or
                         seed_acc.display_name.lower() == handle.lower()):
            seed_acc.display_name = kl.display_name
    if (seed_acc and seed_acc.followers is None and kl.wikidata_followers
            and kl.wikidata_followers_platform == platform):
        seed_acc.followers = kl.wikidata_followers
        seed_acc.raw["followers_source"] = "wikidata"
        seed_acc.raw["wikidata_id"] = kl.wikidata_id
        if kl.wikidata_followers_as_of:
            seed_acc.raw["followers_as_of"] = kl.wikidata_followers_as_of
        as_of = f" as of {kl.wikidata_followers_as_of}" if kl.wikidata_followers_as_of else ""
        seed_acc.errors.append(
            f"Follower count {kl.wikidata_followers:,} came from Wikidata{as_of}, "
            f"not from {platform}'s public page."
        )


def _apply_wikidata_followers(raw: RawProfile, kl: KeylessFindings) -> None:
    """Copy dated Wikidata P8687 counts onto collected surfaces that printed none."""
    readings: dict[str, dict] = {}
    for row in kl.follower_readings or []:
        plat = row.get("platform")
        if plat and row.get("count") and plat not in readings:
            readings[plat] = row
    if (kl.wikidata_followers and kl.wikidata_followers_platform
            and kl.wikidata_followers_platform not in readings):
        readings[kl.wikidata_followers_platform] = {
            "platform": kl.wikidata_followers_platform,
            "count": kl.wikidata_followers,
            "as_of": kl.wikidata_followers_as_of,
        }
    for acc in raw.accounts:
        row = readings.get(acc.platform)
        if not row or acc.followers is not None:
            continue
        acc.followers = int(row["count"])
        acc.raw["followers_source"] = "wikidata"
        if kl.wikidata_id:
            acc.raw["wikidata_id"] = kl.wikidata_id
        as_of = row.get("as_of") or ""
        if as_of:
            acc.raw["followers_as_of"] = as_of
        stamp = f" as of {as_of}" if as_of else ""
        note = (
            f"Follower count {acc.followers:,} came from Wikidata{stamp}, "
            f"not from {acc.platform}'s public page."
        )
        if note not in acc.errors:
            acc.errors.append(note)


def _verify(acc: PlatformAccount, exp, raw: RawProfile, primary: int):
    """Every discovered surface passes the verification gate before it is recorded."""
    key = acc.url.rstrip("/") + ("/" if acc.platform == "instagram" else "")
    source = exp.sources.get(key) or exp.sources.get(acc.url) or "search"
    if source == "seed":
        return v.Verdict(True, 1.0, "The link you supplied.", "seed")
    if source == "wikidata":
        return v.from_wikidata(acc.platform, acc.url)
    conf = exp.probe_confidence.get(key, exp.probe_confidence.get(acc.url, 0.0))
    search_rows = [h for h in raw.search_hits
                   if _account_key(h.url) == _account_key(acc.url)]
    indexed_match = False
    seed_handle = re.sub(r"[^a-z0-9]", "", (raw.seed_handle or "").lower())
    account_handle = re.sub(r"[^a-z0-9]", "", (acc.handle or "").lower())
    if seed_handle and account_handle == seed_handle:
        indexed_match = True
    elif raw.display_name:
        name_start = re.compile(r"^" + re.escape(raw.display_name.strip()) + r"\b", re.I)
        indexed_match = any(name_start.search((h.title or "").strip()) for h in search_rows)
    blob = " ".join([acc.display_name or "", acc.bio or ""]
                    + [c.title for c in acc.content[:20]])
    return v.check(
        platform=acc.platform, url=acc.url,
        from_owned_link=(source == "owned_link"),
        probe_confirmed=(source == "probe"),
        probe_confidence=conf if source == "probe" else 0.0,
        search_confirmed=(source == "search"),
        search_confidence=conf if source == "search" else 0.0,
        indexed_identity_match=indexed_match,
        page_title=acc.display_name, page_text=blob,
        subject_handle=raw.seed_handle or "", subject_name=raw.display_name,
        followers=acc.followers, items=len(acc.content), primary_followers=primary,
    )


async def _collect_one(platform: str, url: str) -> PlatformAccount | None:
    try:
        r = resolve(url)
    except Exception:
        return None
    h = r.handle
    try:
        if platform == "youtube":
            return await yt.collect(h)
        if platform == "instagram":
            return await ig.collect(h)
        if platform == "x":
            return await x_col.collect(h)
        if platform == "linkedin":
            return await li.collect(h, url=url)
        if platform == "topmate":
            return await webcol.collect_topmate(h)
        if platform in ("linktree", "superprofile"):
            return await webcol.collect_linkinbio(url)
        if platform == "telegram":
            return await webcol.collect_telegram(h)
        if platform == "appstore":
            return await webcol.collect_appstore(h)
        if platform == "website":
            return await webcol.collect_website(url)
        if platform == "reddit":
            return await reddit_col.collect(h)
        if platform == "tiktok":
            return await tt.collect(h)
        if platform == "podcast":
            return await pod.collect(url)
        if platform == "bluesky":
            return await bsky.collect(h)
        if platform == "mastodon":
            return await masto.collect(h, url=url)
        if platform == "github":
            return await gh.collect(h, url=url)
        if platform == "soundcloud":
            return await sc.collect(h, url=url)
        if platform == "pinterest":
            return await pin.collect(h, url=url)
        if platform == "hackernews":
            return await hn.collect(h, url=url)
        # Remaining surfaces (Facebook, WhatsApp, …): record the URL honestly.
        # Do not claim an authentication wall for platforms we simply do not collect.
        walled = platform in {"facebook", "whatsapp"}
        return PlatformAccount(
            platform=platform, handle=h, url=url,
            provenance="observed",
            errors=[
                "surface recorded; public data behind an authentication wall"
                if walled else
                f"no public collector is wired for {platform}; surface recorded from URL only"
            ],
            needs_manual=walled,
            raw={"source": "url_only"},
        )
    except Exception as exc:  # noqa: BLE001
        return PlatformAccount(platform=platform, handle=h, url=url,
                               errors=[f"collector failed: {type(exc).__name__}: {exc}"])


async def collect(seed: str, *, run_dorks: bool = True, progress: Progress = _noop) -> RawProfile:
    r = resolve(seed)
    raw = RawProfile(seed_url=r.url, seed_platform=r.platform, seed_handle=r.handle)
    progress("resolving", 5)

    # Pass 1 — the seed account, to learn the display name and the creator's own links.
    seed_acc = await _collect_one(r.platform, r.url)
    if seed_acc:
        seed_acc.raw["verified_via"] = "seed"
        seed_acc.raw["identity_role"] = "primary"
        _add_account(raw, seed_acc)
        raw.display_name = seed_acc.display_name or r.handle
    progress("seed collected", 20)

    owned = list(seed_acc.external_links) if seed_acc else []

    # Pass 2a — probe the handle directly on every platform that can be verified.
    # This needs no search API and is what finds a creator's YouTube channel when the
    # only thing you started with was an Instagram link.
    probes = await probe_handles(r.handle, display_name=raw.display_name,
                                 known={r.platform})
    raw.warnings += probes.notes
    progress("handles probed", 30)

    # Pass 2b — keyless discovery. Official public APIs: Wikipedia, Wikidata, podcasts.
    kl = await gather_keyless(raw.display_name or r.handle, r.handle,
                              seed_platform=r.platform)
    _apply_keyless_identity(raw, seed_acc, kl, r.platform, r.handle)
    raw.keyless = {
        "podcasts": [vars(x) for x in kl.podcasts],
        "wikipedia_title": kl.wikipedia_title,
        "wikipedia_url": kl.wikipedia_url,
        "wikipedia_extract": kl.wikipedia_extract,
        "wikipedia_categories": kl.wikipedia_categories,
        "wikipedia_sections": kl.wikipedia_sections,
        "official_links": kl.official_links,
        "related_searches": kl.related_searches,
        "autocomplete_intents": kl.autocomplete_intents,
        "youtube_candidates": kl.youtube_candidates,
        "wikidata_id": kl.wikidata_id,
        "wikidata_description": kl.wikidata_description,
        "occupations": kl.occupations,
        "citizenships": kl.citizenships,
        "awards": kl.awards,
        "notable_works": kl.notable_works,
        "education": kl.education,
        "employers": kl.employers,
        "work_locations": kl.work_locations,
        "positions": kl.positions,
        "residences": kl.residences,
        "birth_places": kl.birth_places,
        "pseudonyms": kl.pseudonyms,
        "significant_events": kl.significant_events,
        "official_names": kl.official_names,
        "orcid": kl.orcid,
        "orcid_record": kl.orcid_record,
        "official_ids": kl.official_ids,
        "official_id_urls": kl.official_id_urls,
        "filings": kl.filings,
        "musicbrainz_id": kl.musicbrainz_id,
        "musicbrainz": kl.musicbrainz,
        "pageviews": kl.pageviews,
        "spotify_artist": kl.spotify_artist,
        "fields_of_work": kl.fields_of_work,
        "genres": kl.genres,
        "languages": kl.languages,
        "nominations": kl.nominations,
        "participations": kl.participations,
        "memberships": kl.memberships,
        "image_url": kl.image_url,
        "image_source": kl.image_source,
        "display_name": kl.display_name,
    }
    raw.warnings += kl.notes
    progress("keyless discovery", 35)

    # Pass 2c — identity expansion across owned links and the search/dork layer.
    exp = await expand(r.platform, r.handle, r.url,
                       display_name=raw.display_name, owned_links=owned, run_dorks=run_dorks)
    for hit in probes.hits:
        exp.add_target(hit.platform, hit.url, source="probe", confidence=hit.confidence)
        exp.discovered.append(hit.url)
    if kl.youtube_channel_url:
        exp.add_target("youtube", kl.youtube_channel_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.youtube_channel_url)
    if kl.twitter_url:
        exp.add_target("x", kl.twitter_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.twitter_url)
    if kl.tiktok_url:
        exp.add_target("tiktok", kl.tiktok_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.tiktok_url)
    if kl.linkedin_url:
        exp.add_target("linkedin", kl.linkedin_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.linkedin_url)
    if kl.facebook_url:
        exp.add_target("facebook", kl.facebook_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.facebook_url)
    if kl.spotify_url:
        exp.add_target("website", kl.spotify_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.spotify_url)
    if kl.reddit_url:
        exp.add_target("reddit", kl.reddit_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.reddit_url)
    if kl.podcast_url:
        exp.add_target("podcast", kl.podcast_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.podcast_url)
    if kl.bluesky_url:
        exp.add_target("bluesky", kl.bluesky_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.bluesky_url)
    if kl.mastodon_url:
        exp.add_target("mastodon", kl.mastodon_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.mastodon_url)
    if kl.github_url:
        exp.add_target("github", kl.github_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.github_url)
    if kl.soundcloud_url:
        exp.add_target("soundcloud", kl.soundcloud_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.soundcloud_url)
    if kl.pinterest_url:
        exp.add_target("pinterest", kl.pinterest_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.pinterest_url)
    if kl.hackernews_url:
        exp.add_target("hackernews", kl.hackernews_url, source="wikidata", confidence=0.88)
        exp.discovered.append(kl.hackernews_url)
    for site in kl.wikidata_sites[:4]:
        exp.add_target("website", site, source="wikidata", confidence=0.88)
        exp.discovered.append(site)
    # YouTube channels found by searching the name, verified by the collector later.
    for cand in kl.youtube_candidates[:2]:
        # Name ranking discovers a candidate; it does not prove ownership. The
        # verification gate still requires the collected channel to match the identity.
        exp.add_target("youtube", cand["url"], source="search", confidence=0.72)
        exp.discovered.append(cand["url"])
    # Wikipedia citations are independent corroboration, not a creator-controlled link.
    for link in kl.official_links[:6]:
        plat = classify_surface(link)
        if plat:
            exp.add_target(plat, link, source="search", confidence=0.78)
            exp.discovered.append(link)
    if kl.podcasts:
        exp.add_target("podcast", kl.podcasts[0].url, source="search", confidence=0.72)
    raw.search_hits = exp.search_hits
    raw.discovered_urls = exp.discovered
    raw.warnings += exp.warnings
    progress("identity expanded", 40)

    # Pass 3 — collect every additional surface.
    existing_keys = {_account_key(a.url) for a in raw.accounts}
    seen_targets: set[str] = set()
    todo = []
    for p, u in exp.targets:
        key = _account_key(u)
        if key in existing_keys or key in seen_targets:
            continue
        seen_targets.add(key)
        todo.append((p, u))
    results = await asyncio.gather(*(_collect_one(p, u) for p, u in todo), return_exceptions=True)
    primary = max((a.followers or 0) for a in raw.accounts) if raw.accounts else 0
    for res in results:
        if not isinstance(res, PlatformAccount):
            continue
        verdict = _verify(res, exp, raw, primary)
        if verdict.accept:
            res.raw["verified_via"] = verdict.source
            res.raw["verify_confidence"] = round(verdict.confidence, 2)
            _add_account(raw, res)
            primary = max(primary, res.followers or 0)
        else:
            raw.rejected.append({"platform": res.platform, "url": res.url,
                                 "reason": verdict.reason})
    progress("surfaces collected", 70)

    # Pass 4 — follow link-in-bio pages one hop deeper (they map the funnel).
    hop: list[tuple[str, str]] = []
    for acc in list(raw.accounts):
        if acc.platform in ("linktree", "superprofile"):
            for link in acc.external_links[:12]:
                plat = classify_surface(link)
                if plat and _account_key(link) not in {
                        _account_key(a.url) for a in raw.accounts}:
                    exp.add_target(plat, link, source="owned_link")
                    hop.append((plat, link))
    if hop:
        more = await asyncio.gather(*(_collect_one(p, u) for p, u in hop[:8]),
                                    return_exceptions=True)
        primary = max((a.followers or 0) for a in raw.accounts) if raw.accounts else 0
        for res in more:
            if not isinstance(res, PlatformAccount):
                continue
            verdict = _verify(res, exp, raw, primary)
            if verdict.accept:
                res.raw["verified_via"] = verdict.source
                _add_account(raw, res)
            else:
                raw.rejected.append({"platform": res.platform, "url": res.url,
                                     "reason": verdict.reason})
    progress("funnel mapped", 82)

    _apply_wikidata_followers(raw, kl)

    # Final identity/claim audit: account-by-account gates catch obvious false
    # positives; this pass catches contradictions that only appear across surfaces.
    enforce_identity(raw)
    progress("evidence corroborated", 88)

    if any(a.platform == "instagram" and a.needs_manual for a in raw.accounts):
        raw.warnings.append(
            "Instagram post-level and audience data is login-walled. Supply the paste-form to "
            "raise confidence; otherwise private audience dimensions remain unavailable."
        )
    return raw


async def find_competitors(raw: RawProfile):
    """Optional extra stage — costs search queries, so it is opt-in per run."""
    sig = extract(raw)
    self_handles = {(a.handle or "").lower() for a in raw.accounts if a.handle}
    self_handles.add((raw.seed_handle or "").lower())
    return await discover_competitors(
        archetype=sig.archetype,
        topics=[t for t, _ in sig.topic_rank],
        self_handles=self_handles,
        subject_followers=max(sig.followers.values()) if sig.followers else None,
    )


async def collect_comments(raw: RawProfile):
    """Public YouTube comment threads. Needs YOUTUBE_API_KEY; degrades honestly without."""
    from app.engine.collectors.comments import collect_youtube
    return await collect_youtube(raw.all_content())


def analyse(raw: RawProfile, report_id: str, *, competitors=None,
            comment_data=None) -> ReportPayload:
    """Single-creator report: the full thirteen-section payload."""
    return assemble.build(raw, report_id, competitors=competitors,
                          comment_data=comment_data)


def analyse_cohort(payloads: list[ReportPayload], report_id: str,
                   title: str | None = None) -> CohortPayload:
    """Multi-creator report: every single-creator payload plus the comparison layer."""
    from datetime import datetime as _dt
    names = [p.subject_name for p in payloads]
    return CohortPayload(
        report_id=report_id,
        generated_at=_dt.utcnow(),
        title=title or ("Audience Intelligence — " + ", ".join(names[:4])
                        + (f" and {len(names) - 4} more" if len(names) > 4 else "")),
        reports=payloads,
        cohort=cohort.analyse(payloads) if len(payloads) > 1 else None,
    )


async def run(seeds: list[str], *, run_dorks: bool = True, with_competitors: bool = False,
              progress: Progress = _noop) -> tuple[list[RawProfile], list[ReportPayload]]:
    """Collect and analyse one or many seeds. The API and CLI both call this."""
    import uuid
    raws: list[RawProfile] = []
    n = len(seeds)
    for i, seed in enumerate(seeds):
        def sub(stage: str, pct: int, _i=i) -> None:
            progress(f"[{_i + 1}/{n}] {stage}", int((_i + pct / 100) / n * 100))
        raws.append(await collect(seed, run_dorks=run_dorks, progress=sub))

    payloads: list[ReportPayload] = []
    for raw in raws:
        comps = await find_competitors(raw) if with_competitors else None
        cdata = await collect_comments(raw)
        payloads.append(analyse(raw, uuid.uuid4().hex[:12], competitors=comps,
                                comment_data=cdata))
    progress("analysis complete", 100)
    return raws, payloads
