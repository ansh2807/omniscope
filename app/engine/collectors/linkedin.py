"""LinkedIn collector — best-effort public header only.

LinkedIn puts almost everything behind authentication. This collector never logs in
and never guesses private metrics. For a seed or owned-link URL it:

  * tries the public profile HTML for og:title / og:description (headline, name)
  * records the surface so Presence shows LinkedIn as found, not "not discovered"
  * marks needs_manual when follower counts and posts are not publicly readable

Stranger LinkedIn URLs discovered via open web search remain gated by
``discovery.verify.AUTH_WALLED`` — this collector does not weaken that rule.
"""
from __future__ import annotations

import re
from urllib.parse import unquote

from app.engine.http import fetch
from app.engine.numbers import parse_human_count
from app.schemas import PlatformAccount

_TITLE = re.compile(r'<meta\s+property="og:title"\s+content="([^"]*)"', re.I)
_DESC = re.compile(r'<meta\s+property="og:description"\s+content="([^"]*)"', re.I)
_FOLLOWERS = re.compile(
    r"([\d.,]+\s*(?:[KMB]|thousand|million)?)\s+followers?", re.I)


def _num(text: str | None) -> int | None:
    return parse_human_count(text) if text else None


def _clean_title(title: str) -> tuple[str | None, str | None]:
    """Return (display_name, headline) from LinkedIn og:title shapes."""
    t = (title or "").strip()
    if not t:
        return None, None
    # "Name - Headline | LinkedIn" or "Name | LinkedIn"
    t = re.sub(r"\s*\|\s*LinkedIn\s*$", "", t, flags=re.I).strip()
    if " - " in t:
        name, headline = t.split(" - ", 1)
        return name.strip() or None, headline.strip() or None
    return t or None, None


async def collect(handle: str, *, url: str | None = None) -> PlatformAccount:
    handle = unquote((handle or "").strip().strip("/"))
    profile_url = url or f"https://www.linkedin.com/in/{handle}"
    if not profile_url.startswith("http"):
        profile_url = f"https://www.linkedin.com/in/{handle}"

    acc = PlatformAccount(
        platform="linkedin",
        handle=handle or None,
        url=profile_url.rstrip("/") + "/",
        needs_manual=True,
        raw={"source": "public_profile_meta"},
    )

    html = ""
    r = await fetch(profile_url, check_robots=False, use_cache=True)
    if r.ok and r.text:
        html = r.text
    else:
        acc.errors.append(
            f"LinkedIn profile fetch returned status {getattr(r, 'status', 0)}. "
            "Follower counts and posts are behind LinkedIn's authentication wall — "
            "supply them from a logged-in session if you need them in the report.")

    # Browser fallback for public meta when plain HTML is an empty auth shell.
    if (not html or ("authwall" in html.lower() and "og:title" not in html.lower())):
        from app.config import settings as _s
        from app.engine.collectors import browser as br
        if _s.browser_mode in ("always", "auto") and br.enabled():
            rendered = await br.render_page(profile_url, wait_ms=2500)
            if rendered.ok and rendered.text:
                html = rendered.text
                acc.raw["source"] = "browser_render"
                if rendered.title and "og:title" not in html.lower():
                    # Title bar still carries "Name - Headline | LinkedIn" often.
                    name, headline = _clean_title(rendered.title)
                    acc.display_name = acc.display_name or name
                    if headline and not acc.bio:
                        acc.bio = headline

    if html:
        low = html.lower()
        if "authwall" in low or ("signup" in low and "join linkedin" in low):
            acc.errors.append(
                "LinkedIn served an authentication wall for the full profile. "
                "Name/headline may still be available from public meta tags when present.")

        t = _TITLE.search(html)
        if t:
            name, headline = _clean_title(t.group(1))
            acc.display_name = acc.display_name or name
            if headline:
                acc.bio = acc.bio or headline
                acc.keywords = [
                    w.strip() for w in re.split(r"[|/•·,\-]+", headline)
                    if 2 < len(w.strip()) <= 40
                ][:12]

        d = _DESC.search(html)
        if d:
            desc = d.group(1).strip()
            fm = _FOLLOWERS.search(desc)
            if fm:
                acc.followers = _num(fm.group(1))
            if desc and (not acc.bio or len(desc) > len(acc.bio or "")):
                cleaned = re.sub(
                    r"^[\d.,\sKMB]+followers?\s+on\s+LinkedIn\.?\s*",
                    "", desc, flags=re.I).strip()
                if cleaned:
                    acc.bio = cleaned[:500]

    if acc.followers is None:
        acc.errors.append(
            "LinkedIn does not publish follower counts to logged-out collectors. "
            "The profile URL is recorded; paste the follower count from a logged-in "
            "session if you need it in Presence.")
    if not acc.display_name and not acc.bio:
        acc.raw["source"] = "url_only"
        acc.errors.append(
            "No public LinkedIn meta tags were readable. Surface recorded from the URL only.")

    return acc


# Optional analyst paste fields (mirrors Instagram's pattern; wired when UI wants them).
MANUAL_FIELDS: list[dict[str, str]] = [
    {"key": "followers", "label": "LinkedIn followers", "type": "number",
     "help": "From the public profile header while logged in."},
    {"key": "display_name", "label": "Display name", "type": "text", "help": ""},
    {"key": "bio", "label": "Headline / about", "type": "textarea",
     "help": "The LinkedIn headline and a short about blurb."},
]
