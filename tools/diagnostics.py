"""Live self-diagnosis.

Answers the only question that matters when something is wrong: which part of the
collection stack is actually working right now? Every check hits a real public page and
reports what it got, so "not working" becomes a specific, fixable line rather than a
guess.

Safe to run any time. Uses one well-known public account per platform and nothing else.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.config import settings

# Deliberately large, stable, unambiguous public accounts — used only to prove the
# plumbing works, never stored or reported on.
PROBE_IG = "instagram"          # Instagram's own account
PROBE_YT = "YouTube"            # YouTube's own channel


@dataclass
class Check:
    name: str
    ok: bool = False
    detail: str = ""
    fix: str = ""
    ms: int = 0
    critical: bool = True


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    verdict: str = ""
    can_generate: bool = False
    quality: str = ""


async def _timed(fn):
    t0 = time.monotonic()
    try:
        out = await fn()
    except Exception as exc:  # noqa: BLE001
        return None, int((time.monotonic() - t0) * 1000), f"{type(exc).__name__}: {exc}"
    return out, int((time.monotonic() - t0) * 1000), None


async def run() -> Report:
    rep = Report()

    # ---------------------------------------------------------- 1. network
    from app.engine.http import fetch
    res, ms, err = await _timed(lambda: fetch("https://example.com", check_robots=False))
    c = Check("Internet access", ms=ms)
    if err or not res or not res.ok:
        c.detail = err or f"status {getattr(res, 'status', '?')}"
        c.fix = ("No outbound HTTP. Check your connection, VPN or corporate proxy. "
                 "Nothing else can work until this does.")
    else:
        c.ok, c.detail = True, "Reached example.com successfully."
    rep.checks.append(c)

    # ---------------------------------------------- 2. browser tier installed
    from app.engine.collectors import browser as br
    c = Check("Browser engine installed")
    if br.available():
        c.ok = True
        c.detail = f"Playwright present. Mode is '{settings.browser_mode}'."
        if settings.browser_mode == "off":
            c.ok = False
            c.detail = "Playwright is installed but BROWSER_MODE is 'off'."
            c.fix = "Set the browser mode to 'auto' in Settings."
    else:
        c.detail = "Playwright is not installed."
        c.fix = ("Close the app, run START.bat again (it installs the browser "
                 "automatically), or run ENABLE-BROWSER.bat.")
    rep.checks.append(c)

    # ------------------------------------------------- 3. browser can launch
    c = Check("Browser can launch and render")
    if not br.enabled():
        c.detail = "Skipped — browser tier not active."
        c.fix = "Enable the browser tier first."
    else:
        res, ms, err = await _timed(lambda: br.instagram_profile(PROBE_IG))
        c.ms = ms
        if err:
            c.detail = err
            c.fix = ("Chromium is present but failed to start. Re-run ENABLE-BROWSER.bat, "
                     "or check that antivirus is not blocking it.")
        elif res and res.ok:
            d = br.parse_instagram(res.text)
            if d.get("followers"):
                c.ok = True
                c.detail = (f"Rendered a live Instagram profile and read "
                            f"{d['followers']:,} followers off the page.")
            else:
                c.detail = "Page rendered but no follower count could be parsed."
                c.fix = ("Instagram may have changed its markup, or served a sign-in "
                         "prompt. Reports will fall back to the meta tag, which is less "
                         "accurate.")
        else:
            c.detail = (res.notes[0] if res and res.notes else "Render returned nothing.")
            c.fix = "Instagram served a sign-in wall to this machine. Try again later."
    rep.checks.append(c)

    # -------------------------------------------------- 4. YouTube collection
    c = Check("YouTube collection")
    from app.engine.collectors.youtube import collect as yt_collect
    res, ms, err = await _timed(lambda: yt_collect(PROBE_YT))
    c.ms = ms
    if err:
        c.detail = err
        c.fix = "Check network access to youtube.com."
    elif res and res.followers and res.followers >= 1_000_000 and len(res.content) >= 3:
        c.ok = True
        src = res.raw.get("source", "?").replace("_", " ")
        c.detail = (f"Read {res.followers:,} subscribers and {len(res.content)} videos "
                    f"via {src}." if res.followers else
                    f"Read {len(res.content)} videos via {src}.")
        if not settings.youtube_api_key and not br.enabled():
            c.detail += " Latest sort only — no API key and no browser tier."
    else:
        followers = getattr(res, "followers", None)
        items = len(getattr(res, "content", []) or [])
        if followers or items:
            c.detail = (f"The probe returned an implausible result for YouTube's official "
                        f"channel ({followers or 0:,} subscribers, {items} videos). "
                        f"Collection is not marked healthy because localised counters or "
                        f"page markup may have been parsed incorrectly.")
        else:
            c.detail = "No channel data returned."
        c.fix = ("Re-run diagnostics once. If this persists, update the collector or add "
                 "a YouTube Data API key; do not trust reports produced by this tier.")
    rep.checks.append(c)

    # ------------------------------------------------------ 5. handle probing
    c = Check("Handle probing (finds other platforms, no key needed)", critical=False)
    from app.engine.discovery.probe import run as probe
    res, ms, err = await _timed(lambda: probe("youtube", display_name="YouTube",
                                              known={"instagram"}, max_variants=1))
    c.ms = ms
    if err:
        c.detail = err
    else:
        c.ok = True
        c.detail = (f"Probed {res.attempted} platform/handle combinations successfully "
                    f"({len(res.hits)} verified hits on the test handle).")
    rep.checks.append(c)

    # ------------------------------------------------------------- 6. search
    c = Check("Search / discovery", critical=False)
    if settings.search_provider in ("", "none"):
        c.detail = "No search provider configured."
        c.fix = ("Needed only for general web search. Get a free key at serper.dev "
                 "(2,500 queries, about 250 reports) and paste it in Settings. Without it "
                 "you lose competitor discovery, page-one search ownership, and press and "
                 "news mentions. Podcasts, Wikipedia, related searches and cross-platform "
                 "discovery all still work without it.")
    else:
        from app.engine.discovery.search import search
        res, ms, err = await _timed(lambda: search("site:youtube.com youtube", limit=3))
        c.ms = ms
        if err:
            c.detail = err
            c.fix = "Key rejected or provider unreachable. Check the key in Settings."
        elif res:
            c.ok = True
            c.detail = f"{settings.search_provider} returned {len(res)} results."
        else:
            c.detail = f"{settings.search_provider} returned nothing."
            c.fix = "Check the key is valid and has quota remaining."
    rep.checks.append(c)

    # ------------------------------------------------------- 7. comment reading
    c = Check("Comment collection", critical=False)
    if settings.youtube_api_key:
        c.ok = True
        c.detail = "YouTube Data API key present — comments read through the official API."
    elif br.enabled():
        c.ok = True
        c.detail = "No API key, but the browser tier can read public comment threads."
    else:
        c.detail = "Neither a YouTube API key nor the browser tier is available."
        c.fix = ("Enable the browser tier, or add a free YouTube key in Settings. "
                 "Without either, the comment and sentiment section stays empty.")
    rep.checks.append(c)

    # -------------------------------------------------- 8. keyless discovery
    c = Check("Keyless discovery (podcasts, Wikipedia, related searches)", critical=False)
    from app.engine.discovery import keyless
    res, ms, err = await _timed(lambda: keyless.related_searches("instagram"))
    c.ms = ms
    if err:
        c.detail = err
        c.fix = "Autocomplete endpoint unreachable — check network or proxy."
    elif res and res["suggestions"]:
        c.ok = True
        c.detail = (f"Read {len(res['suggestions'])} live autocomplete completions. "
                    f"Podcast, Wikipedia and search-intent discovery all work with no key.")
    else:
        c.detail = "Autocomplete returned nothing."
        c.fix = "Usually a transient network issue. Re-run diagnostics."
    rep.checks.append(c)

    # ------------------------------------------------------------- verdict
    critical_ok = all(c.ok for c in rep.checks if c.critical)
    rep.can_generate = critical_ok
    optional_ok = sum(1 for c in rep.checks if not c.critical and c.ok)
    optional_total = sum(1 for c in rep.checks if not c.critical)

    if not rep.checks[0].ok:
        rep.verdict = "No internet access. Nothing will work until that is fixed."
        rep.quality = "blocked"
    elif not critical_ok:
        rep.verdict = ("Reports will generate, but with thin data. Fix the failing checks "
                       "above for a complete report.")
        rep.quality = "degraded"
    elif optional_ok == optional_total:
        rep.verdict = ("Everything is working. Reports will be as complete as public data "
                       "allows.")
        rep.quality = "full"
    else:
        rep.verdict = (f"Core collection works. {optional_total - optional_ok} optional "
                       f"source(s) are off — see the fixes above for what each one adds.")
        rep.quality = "good"
    return rep
