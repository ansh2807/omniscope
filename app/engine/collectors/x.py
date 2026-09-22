"""X (Twitter) collector — public profile surface only.

WHAT WE COLLECT AUTOMATICALLY (no login, no guest-token tricks):
  * display name, bio / description, verification flag when present
  * follower and following counts from X's public syndication widget endpoint
    (the same JSON a follow-button embed loads without authentication)
  * a small sample of recent post text when the public profile HTML exposes it

WHAT WE DO NOT DO:
  * no login, no cookies, no CAPTCHA solving, no proxy rotation
  * no private analytics (impressions, audience demographics)

If the syndication endpoint or the public HTML is empty, the account is still recorded
with an honest error so Presence shows the surface rather than "not found".
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from app.engine.http import fetch
from app.engine.numbers import parse_human_count
from app.schemas import ContentItem, PlatformAccount

_TITLE = re.compile(r'<meta\s+property="og:title"\s+content="([^"]*)"', re.I)
_DESC = re.compile(r'<meta\s+property="og:description"\s+content="([^"]*)"', re.I)
_COUNT_PAIR = re.compile(
    r"([\d.,]+\s*[KMB]?)\s+Followers?.*?([\d.,]+\s*[KMB]?)\s+Following",
    re.I | re.S,
)
# "Name (@handle) on X" / "Name (@handle) / X"
_NAME_AT = re.compile(r"^(.+?)\s*\(@([A-Za-z0-9_]+)\)")


def _num(text: str | int | float | None) -> int | None:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    return parse_human_count(str(text))


async def _via_syndication(handle: str) -> PlatformAccount | None:
    """Public embed endpoint — no auth, used by X's own follow-button widget."""
    url = ("https://cdn.syndication.twimg.com/widgets/followbutton/info.json"
           f"?screen_names={quote(handle)}")
    r = await fetch(url, check_robots=False, use_cache=True,
                    headers={"Accept": "application/json"})
    if not r.ok or not (r.text or "").strip():
        return None
    try:
        data = json.loads(r.text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or not data:
        return None
    row: dict[str, Any] = data[0] if isinstance(data[0], dict) else {}
    screen = (row.get("screen_name") or handle).lstrip("@")
    if not screen:
        return None
    acc = PlatformAccount(
        platform="x",
        handle=screen,
        url=f"https://x.com/{screen}",
        display_name=row.get("name") or None,
        bio=(row.get("description") or None),
        followers=_num(row.get("followers_count")),
        following=_num(row.get("friends_count")),
        verified=bool(row.get("verified")) or None,
        raw={
            "source": "syndication_followbutton",
            "statuses_count": row.get("statuses_count"),
            "location": row.get("location") or "",
        },
    )
    if row.get("statuses_count") is not None:
        acc.posts = _num(row.get("statuses_count"))
    return acc


async def _via_html(handle: str) -> PlatformAccount | None:
    """Fallback: public profile HTML meta tags (often thin, sometimes login-walled)."""
    for host in ("x.com", "twitter.com"):
        url = f"https://{host}/{handle}"
        r = await fetch(url, check_robots=False, use_cache=True)
        if not r.ok or not r.text:
            continue
        low = r.text.lower()
        if "this account doesn" in low and "exist" in low:
            return None
        if "account suspended" in low:
            acc = PlatformAccount(
                platform="x", handle=handle, url=f"https://x.com/{handle}",
                errors=["account suspended"], raw={"source": "public_profile_meta"})
            return acc
        acc = PlatformAccount(
            platform="x", handle=handle, url=f"https://x.com/{handle}",
            raw={"source": "public_profile_meta"})
        t = _TITLE.search(r.text)
        if t:
            title = t.group(1).strip()
            m = _NAME_AT.search(title)
            if m:
                acc.display_name = m.group(1).strip() or None
                acc.handle = m.group(2) or handle
            else:
                acc.display_name = (title.split(" on X")[0].split(" / X")[0]
                                    .split("(@")[0].strip() or None)
        d = _DESC.search(r.text)
        if d:
            desc = d.group(1).strip()
            c = _COUNT_PAIR.search(desc)
            if c:
                acc.followers = _num(c.group(1))
                acc.following = _num(c.group(2))
            # Description often is "bio" after counts, or the bio alone.
            if "Followers" in desc and " - " in desc:
                acc.bio = desc.split(" - ", 1)[-1].strip() or None
            elif "Followers" not in desc:
                acc.bio = desc or None
        # Lightweight public tweet titles when present in SSR payload.
        for tw in re.findall(r'"full_text"\s*:\s*"((?:\\.|[^"\\]){12,280})"', r.text)[:12]:
            text = (tw.encode("utf-8").decode("unicode_escape", errors="ignore")
                    .replace("\n", " ").strip())
            if text and len(text) > 8:
                acc.content.append(ContentItem(
                    platform="x", title=text[:220], kind="post",
                    url=f"https://x.com/{acc.handle}"))
        if acc.display_name or acc.followers is not None or acc.bio:
            return acc
    return None


async def _via_browser(handle: str) -> PlatformAccount | None:
    """Logged-out browser render of the public profile header."""
    from app.engine.collectors import browser as br
    if not br.enabled():
        return None
    r = await br.render_page(f"https://x.com/{handle}", wait_ms=2800)
    if not r.ok or not r.text:
        return None
    text = r.text
    acc = PlatformAccount(
        platform="x", handle=handle, url=f"https://x.com/{handle}",
        raw={"source": "browser_render"})
    if r.title:
        m = _NAME_AT.search(r.title)
        if m:
            acc.display_name = m.group(1).strip() or None
            acc.handle = m.group(2) or handle
        else:
            acc.display_name = (r.title.replace(" on X", "").split("(@")[0]
                                .strip() or None)
    fm = re.search(r"([\d.,]+\s*[KMB]?)\s*Followers?", text, re.I)
    if fm:
        acc.followers = _num(fm.group(1))
    gm = re.search(r"([\d.,]+\s*[KMB]?)\s*Following", text, re.I)
    if gm:
        acc.following = _num(gm.group(1))
    if acc.followers is None and not acc.display_name:
        return None
    return acc


async def collect(handle: str) -> PlatformAccount:
    handle = (handle or "").strip().lstrip("@")
    if not handle:
        return PlatformAccount(
            platform="x", handle="", url="https://x.com/",
            errors=["empty handle"], raw={"source": "url_only"})

    synd = await _via_syndication(handle)
    if synd and (synd.followers is not None or synd.bio or synd.display_name):
        # Enrich with any public post titles the HTML still exposes.
        html = await _via_html(handle)
        if html and html.content and not synd.content:
            synd.content = html.content[:12]
        if html and html.bio and not synd.bio:
            synd.bio = html.bio
        return synd

    html = await _via_html(handle)
    if html and (html.followers is not None or html.bio or html.display_name):
        return html

    from app.config import settings as _s
    if _s.browser_mode in ("always", "auto"):
        rendered = await _via_browser(handle)
        if rendered:
            return rendered

    # Surface still recorded — Presence can show the seed URL honestly.
    acc = PlatformAccount(
        platform="x", handle=handle, url=f"https://x.com/{handle}",
        provenance="observed",
        needs_manual=False,
        errors=[
            "X public profile did not return follower counts or bio over plain HTTP. "
            "The surface is recorded from the URL you supplied; enable the browser tier "
            "or re-run later if X is rate-limiting this network."
        ],
        raw={"source": "url_only"},
    )
    return acc
