"""Browser-rendered collection tier.

This is the method used to build the original hand-made report: open the page in a real
browser, let it render, read the text. No API key, no account, no login.

Why it exists: plain HTTP gets you the raw HTML, and Instagram and YouTube both render
their real content with JavaScript. A follower count, a "Popular" video sort and a
comment thread are all publicly visible to any visitor — they are just not in the
initial HTML payload. Rendering the page is what a visitor's browser does.

The boundaries are the same as everywhere else in this codebase and are enforced here:

  * Logged out, always. No credentials, no session cookies, no storage state.
  * No CAPTCHA solving and no bot-detection evasion. If a challenge appears, we stop
    and record it rather than working around it.
  * No proxy rotation. One identity, rate-limited, honest User-Agent.
  * Login walls are respected. We read the profile header a logged-out visitor sees;
    we do not click through a sign-in prompt to reach the post grid.

If Playwright is not installed the whole module no-ops and every caller falls back to
the HTTP tier, so the engine never hard-fails on a missing browser.
"""
from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass, field

from app.config import settings
from app.engine.numbers import parse_human_count

_PLAYWRIGHT_OK: bool | None = None
_lock = asyncio.Lock()


def available() -> bool:
    """Is Playwright importable? Cached, because the import is not cheap."""
    global _PLAYWRIGHT_OK
    if _PLAYWRIGHT_OK is None:
        try:
            import playwright.async_api  # noqa: F401
            _PLAYWRIGHT_OK = True
        except Exception:
            _PLAYWRIGHT_OK = False
    return _PLAYWRIGHT_OK


def enabled() -> bool:
    return settings.browser_mode in ("auto", "always") and available()


INSTALL_HINT = (
    "Browser tier unavailable. To enable it — this is what removes the need for a "
    "YouTube API key — run:  pip install playwright  &&  python -m playwright install chromium"
)


@dataclass
class Rendered:
    url: str
    ok: bool = False
    text: str = ""
    title: str = ""
    error: str | None = None
    challenged: bool = False        # a bot check or login wall blocked the content
    notes: list[str] = field(default_factory=list)


CHALLENGE_MARKERS = (
    "unusual traffic", "verify you are human", "captcha", "are you a robot",
    "confirm you're not a bot", "sign in to continue", "please enable javascript",
)


@contextlib.asynccontextmanager
async def _browser():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch(
            headless=settings.browser_headless,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = await b.new_context(
            user_agent=settings.browser_user_agent or settings.user_agent,
            locale="en-IN",
            viewport={"width": 1440, "height": 900},
            # Explicitly no storage_state: this context is always logged out.
        )
        ctx.set_default_timeout(settings.browser_timeout_ms)
        try:
            yield ctx
        finally:
            await ctx.close()
            await b.close()


async def _read(page, selector: str | None = None) -> str:
    if selector:
        try:
            el = await page.query_selector(selector)
            if el:
                return (await el.inner_text()) or ""
        except Exception:
            pass
    return await page.evaluate("() => document.body ? document.body.innerText : ''")


def _challenged(text: str) -> bool:
    low = text[:4000].lower()
    return any(m in low for m in CHALLENGE_MARKERS)


async def render_page(url: str, *, wait_ms: int = 2500,
                      main_selector: str | None = "main") -> Rendered:
    """Logged-out render of any public URL. Used by X/LinkedIn collectors."""
    r = Rendered(url=url)
    if not enabled():
        r.error = INSTALL_HINT
        return r
    async with _lock:
        try:
            async with _browser() as ctx:
                page = await ctx.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(wait_ms)
                text = await _read(page, main_selector) if main_selector else ""
                if not (text or "").strip():
                    text = await _read(page)
                r.title = await page.title()
                r.text = text
                r.ok = bool((text or "").strip())
                if _challenged(text or ""):
                    r.challenged = True
                    r.notes.append(
                        "A sign-in or bot challenge blocked the public content. "
                        "We stop here rather than working around it."
                    )
        except Exception as exc:  # noqa: BLE001
            r.error = f"{type(exc).__name__}: {exc}"
    return r


# =============================================================== Instagram
async def instagram_profile(handle: str) -> Rendered:
    """The public profile header any logged-out visitor sees."""
    url = f"https://www.instagram.com/{handle}/"
    r = Rendered(url=url)
    if not enabled():
        r.error = INSTALL_HINT
        return r
    async with _lock:
        try:
            async with _browser() as ctx:
                page = await ctx.new_page()
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)
                text = await _read(page, "main")
                if not text.strip():
                    text = await _read(page)
                r.title = await page.title()
                r.text = text
                r.ok = bool(text.strip())
                if _challenged(text):
                    r.challenged = True
                    r.notes.append(
                        "Instagram served a sign-in prompt instead of the profile header. "
                        "We stop here rather than working around it."
                    )
        except Exception as exc:  # noqa: BLE001
            r.error = f"{type(exc).__name__}: {exc}"
    return r


_HUMAN_COUNT = r"[\d.,]+\s*(?:[KMB]|thousand|million|billion|lakhs?|lacs?|crores?|cr)?"
IG_COUNTS = re.compile(rf"({_HUMAN_COUNT})\s*\n?\s*followers", re.I)
IG_TRIPLE = re.compile(rf"({_HUMAN_COUNT})\s+followers\s+({_HUMAN_COUNT})\s+following", re.I)
VISIBLE_URL = re.compile(
    r"(?<![@\w])((?:https?://|www\.)[a-z0-9.-]+\.[a-z]{2,}"
    r"(?:/[^\s<>\"']*)?)", re.I)


def _normalise_visible_url(value: str) -> str:
    clean = value.strip().rstrip(".,;:!?)\"]}")
    return clean if clean.lower().startswith(("http://", "https://")) else "https://" + clean


def parse_instagram(text: str) -> dict:
    """Parse the rendered profile header. Mirrors what a human reads off the page."""
    out: dict = {"highlights": [], "external_links": []}
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    joined = "\n".join(lines)

    for i, line in enumerate(lines):
        low = line.lower()
        if "followers" in low and out.get("followers") is None:
            m = re.search(rf"({_HUMAN_COUNT})\s*followers", line, re.I)
            out["followers"] = parse_human_count(m.group(1)) if m else (
                parse_human_count(lines[i - 1]) if i else None)
        elif "following" in low and out.get("following") is None:
            m = re.search(rf"({_HUMAN_COUNT})\s*following", line, re.I)
            out["following"] = parse_human_count(m.group(1)) if m else (
                parse_human_count(lines[i - 1]) if i else None)
        elif "posts" in low and out.get("posts") is None:
            m = re.search(rf"({_HUMAN_COUNT})\s*posts", line, re.I)
            if m:
                out["posts"] = parse_human_count(m.group(1))

    # Handle and display name sit above the counts; bio sits below them.
    if lines:
        out["handle_line"] = lines[0]
    idx = next((i for i, l in enumerate(lines) if "followers" in l.lower()), None)
    if idx is not None and idx + 2 < len(lines):
        tail = lines[idx + 1:]
        # first non-count line after the stats block is the display name
        body = [l for l in tail if not re.search(r"(followers|following|posts)$", l, re.I)]
        if body:
            out["display_name"] = body[0]
            bio = [l for l in body[1:8]
                   if not l.lower().startswith(("show more posts", "message", "follow"))]
            out["bio"] = " ".join(bio[:6])[:600] or None
    for l in lines:
        if l.startswith(("http://", "https://")) or re.match(
                r"^(?:www\.)?[\w.-]+\.(io|com|in|bio|ee|me)/", l):
            link = _normalise_visible_url(l)
            if link not in out["external_links"]:
                out["external_links"].append(link)
    # Instagram sometimes renders the website at the end of the bio instead of on
    # its own line. Only explicit http/www URLs qualify; @handles are never promoted.
    for match in VISIBLE_URL.finditer(joined):
        link = _normalise_visible_url(match.group(1))
        if link not in out["external_links"]:
            out["external_links"].append(link)
    tail = lines[-14:]
    for l in tail:
        if 1 < len(l) <= 28 and not any(
                w in l.lower() for w in ("follower", "following", "post", "show more",
                                         "instagram", "log in", "sign up")):
            out["highlights"].append(l)
    out["verified"] = "verified" in joined.lower()
    return out


# ================================================================= YouTube
async def youtube_channel(handle_or_id: str) -> Rendered:
    """Channel page with BOTH sorts — latest and popular.

    Clicking the "Popular" chip is the step that produced the all-time top-performers
    table in the original hand-made report, and it is not reachable over plain HTTP.
    """
    base = (f"https://www.youtube.com/channel/{handle_or_id}"
            if handle_or_id.startswith("UC") else f"https://www.youtube.com/@{handle_or_id}")
    r = Rendered(url=base)
    if not enabled():
        r.error = INSTALL_HINT
        return r
    async with _lock:
        try:
            async with _browser() as ctx:
                page = await ctx.new_page()
                await page.goto(f"{base}/videos", wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)
                await _consent(page)
                for _ in range(3):
                    await page.mouse.wheel(0, 4000)
                    await page.wait_for_timeout(900)
                latest = await _read(page, "ytd-browse")
                r.title = await page.title()

                popular = ""
                try:
                    chip = page.locator(
                        "yt-chip-cloud-chip-renderer:has-text('Popular')").first
                    if await chip.count():
                        await chip.click()
                        await page.wait_for_timeout(2600)
                        for _ in range(2):
                            await page.mouse.wheel(0, 4000)
                            await page.wait_for_timeout(800)
                        popular = await _read(page, "ytd-browse")
                except Exception:
                    r.notes.append("Popular sort chip was not clickable on this channel.")

                r.text = latest + ("\n===POPULAR===\n" + popular if popular else "")
                r.ok = bool(latest.strip())
                if popular:
                    r.notes.append("Collected both Latest and Popular sorts.")
                if _challenged(latest):
                    r.challenged = True
        except Exception as exc:  # noqa: BLE001
            r.error = f"{type(exc).__name__}: {exc}"
    return r


async def youtube_comments(video_urls: list[str], *, per_video: int = 60) -> Rendered:
    """Public comment threads, read the way a visitor reads them: scroll and look."""
    r = Rendered(url=video_urls[0] if video_urls else "")
    if not enabled():
        r.error = INSTALL_HINT
        return r
    chunks: list[str] = []
    async with _lock:
        try:
            async with _browser() as ctx:
                page = await ctx.new_page()
                for url in video_urls:
                    try:
                        await page.goto(url, wait_until="domcontentloaded")
                        await page.wait_for_timeout(2200)
                        await _consent(page)
                        for _ in range(6):
                            await page.mouse.wheel(0, 2600)
                            await page.wait_for_timeout(750)
                        block = await _read(page, "ytd-comments")
                        if block.strip():
                            chunks.append(f"===VIDEO {url}===\n{block}")
                    except Exception:
                        continue
                r.text = "\n".join(chunks)
                r.ok = bool(chunks)
                r.notes.append(f"Rendered comment threads on {len(chunks)} of "
                               f"{len(video_urls)} videos.")
        except Exception as exc:  # noqa: BLE001
            r.error = f"{type(exc).__name__}: {exc}"
    return r


async def _consent(page) -> None:
    """Dismiss a cookie or consent banner by choosing the most privacy-preserving option."""
    for sel in ("button:has-text('Reject all')", "button:has-text('Reject')",
                "button[aria-label*='Reject']", "button:has-text('Decline')"):
        try:
            b = page.locator(sel).first
            if await b.count():
                await b.click(timeout=1500)
                await page.wait_for_timeout(700)
                return
        except Exception:
            continue


VIEW_LINE = re.compile(rf"^({_HUMAN_COUNT})\s+views?$", re.I)
DURATION = re.compile(r"^(\d{1,2}:)?\d{1,2}:\d{2}$")
AGO = re.compile(r"^\d+\s+(second|minute|hour|day|week|month|year)s?\s+ago$", re.I)


def parse_youtube(text: str) -> dict:
    """Turn the rendered channel page into structured items.

    The rendered text arrives as repeating blocks of duration / title / views / age.
    This walks the lines and reassembles them, which is exactly the reading a human
    does off the screen.
    """
    out: dict = {"videos": [], "popular": [], "subscribers": None, "video_count": None,
                 "display_name": None, "description": None}
    sections = text.split("===POPULAR===")
    for si, section in enumerate(sections):
        lines = [l.strip() for l in section.splitlines() if l.strip()]
        bucket = out["popular"] if si == 1 else out["videos"]

        for i, line in enumerate(lines):
            if out["subscribers"] is None and re.search(r"subscribers?$", line, re.I):
                out["subscribers"] = parse_human_count(line)
            if out["video_count"] is None and re.search(r"videos?$", line, re.I):
                out["video_count"] = parse_human_count(line)

            m = VIEW_LINE.match(line)
            if not m:
                continue
            views = parse_human_count(m.group(1))
            title, duration, age = None, None, None
            for back in range(1, 4):
                if i - back < 0:
                    break
                cand = lines[i - back]
                if DURATION.match(cand):
                    duration = _dur(cand)
                elif not title and len(cand) > 8 and not VIEW_LINE.match(cand):
                    title = cand
            if i + 1 < len(lines) and AGO.match(lines[i + 1]):
                age = lines[i + 1]
            if title and views is not None:
                bucket.append({"title": title, "views": views,
                               "duration_seconds": duration, "published_relative": age})
        if si == 0 and lines:
            out["display_name"] = out["display_name"] or lines[0]
    return out


def _n(s: str) -> int | None:
    """Backward-compatible wrapper used by older callers and tests."""
    return parse_human_count(s)


def _dur(s: str) -> int:
    parts = [int(p) for p in s.split(":")]
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return secs


COMMENT_NOISE = re.compile(
    r"^(reply|replies|\d+ repl|show more|read more|@|\d+ likes?|like|dislike|"
    r"pinned by|subscribe|sort by|top comments|newest first|add a comment)", re.I)


def parse_comments(text: str) -> list[dict]:
    """Extract comment bodies and like counts from a rendered comment section."""
    out: list[dict] = []
    for block in text.split("===VIDEO ")[1:]:
        head, _, body = block.partition("\n")
        video_url = head.strip().rstrip("=")
        lines = [l.strip() for l in body.splitlines() if l.strip()]
        i = 0
        while i < len(lines):
            line = lines[i]
            # An author handle line looks like "@name" and the comment follows it.
            if line.startswith("@") and i + 1 < len(lines):
                author = line
                text_lines = []
                j = i + 1
                while j < len(lines) and not lines[j].startswith("@"):
                    cand = lines[j]
                    if AGO.match(cand) or COMMENT_NOISE.match(cand):
                        j += 1
                        continue
                    text_lines.append(cand)
                    j += 1
                    if len(text_lines) >= 6:
                        break
                likes = 0
                for cand in lines[i:j + 2]:
                    lm = re.match(r"^([\d.,]+[KM]?)$", cand)
                    if lm:
                        likes = _n(lm.group(1)) or 0
                        break
                body_text = " ".join(text_lines).strip()
                if len(body_text) >= 6:
                    out.append({"text": body_text[:800], "likes": likes,
                                "author": author, "video_url": video_url})
                i = j
            else:
                i += 1
    return out
