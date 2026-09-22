"""Instagram collector — hybrid mode.

WHAT WE COLLECT AUTOMATICALLY (all genuinely public, no auth):
  * display name, bio, verification badge, external link
  * follower / following / post counts when the public HTML prints them
    (embedded profile JSON or og:description)
  * story-highlight titles when present in the server-rendered payload

WHAT WE DO NOT DO:
  * we do not log in, carry session cookies, rotate proxies, or solve challenges
  * we do not scrape post grids, reel view counts, likes, comments, or audience
    demographics — all of that sits behind Instagram's login wall

A missing follower count stays unavailable. The report is still built. Optional
analyst paste upgrades those fields to observed.

If you later license a commercial provider (Apify / Phyllo / Modash / RapidAPI), set
IG_PROVIDER=generic_http and point IG_PROVIDER_URL at it — `_via_provider` normalises
any JSON shape with a small field map, so you don't have to touch the rest of the engine.
"""
from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any

from app.config import settings
from app.engine.collectors import browser as br
from app.engine.http import fetch
from app.engine.numbers import parse_human_count
from app.schemas import ContentItem, PlatformAccount

_COUNT_TEXT = r"[\d.,]+\s*(?:[KMB]|thousand|million|billion|lakhs?|lacs?|crores?|cr)?"
_COUNTS = re.compile(
    rf"({_COUNT_TEXT})\s+Followers?,\s+({_COUNT_TEXT})\s+Following,\s+({_COUNT_TEXT})\s+Posts?",
    re.I)
_COUNTS_LOOSE = re.compile(
    rf"({_COUNT_TEXT})\s+Followers?", re.I)
_JSON_FOLLOWERS = (
    re.compile(r'"edge_followed_by"\s*:\s*\{\s*"count"\s*:\s*(\d+)'),
    re.compile(r'"follower_count"\s*:\s*(\d+)'),
    re.compile(r'"followers_count"\s*:\s*(\d+)'),
)
_JSON_FOLLOWING = (
    re.compile(r'"edge_follow"\s*:\s*\{\s*"count"\s*:\s*(\d+)'),
    re.compile(r'"following_count"\s*:\s*(\d+)'),
)
_JSON_POSTS = (
    re.compile(r'"edge_owner_to_timeline_media"\s*:\s*\{\s*"count"\s*:\s*(\d+)'),
    re.compile(r'"media_count"\s*:\s*(\d+)'),
)
_COUNT_RANK = {
    "json": 3,
    "browser_render": 2,
    "og_description": 1,
    "public_profile_meta": 0,
}
_MISSING_FOLLOWERS = (
    "Instagram did not print a follower count to this logged-out request. "
    "Public profiles often serve a login wall to automated clients; the report "
    "continues and that field stays unavailable."
)


def _suspicious(value: int, raw_text: str) -> bool:
    """Is this a rounded placeholder rather than a real reading?

    '10M' is one significant figure on an eight-figure number — it could be anything from
    9.5M to 10.5M, and Instagram serves exactly that shape. A real count like '1,743,208'
    or even '1.7M' carries more information and is trusted.
    """
    txt = raw_text.strip()
    if re.fullmatch(r"\d+[KMB]", txt, re.I):          # "10M", "500K" — one sig fig
        return value >= 100_000
    return value >= 1_000_000 and value % 1_000_000 == 0


def _num(t: str) -> int | None:
    return parse_human_count(t)


def _meta_attr(html: str, *names: str) -> str | None:
    """Read a meta content value regardless of attribute order or quote style."""
    for name in names:
        n = re.escape(name)
        pats = (
            rf'<meta\b[^>]*(?:property|name)=["\']{n}["\'][^>]*\bcontent=["\']([^"\']*)["\']',
            rf'<meta\b[^>]*\bcontent=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{n}["\']',
        )
        for pat in pats:
            m = re.search(pat, html, re.I)
            if m:
                return html_lib.unescape(m.group(1))
    return None


def _json_str(html: str, key: str) -> str | None:
    m = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', html)
    if not m:
        return None
    raw = m.group(1)
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw.replace("\\/", "/").replace('\\"', '"') or None


def _first_int(html: str, patterns: tuple[re.Pattern[str], ...]) -> int | None:
    for pat in patterns:
        m = pat.search(html)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def parse_public_html(html: str) -> dict[str, Any]:
    """Pull public header fields from whatever Instagram actually printed.

    This is not a login, a challenge solver, or a post-grid scrape. It only reads
    numbers and strings already present in the response body.
    """
    out: dict[str, Any] = {
        "highlights": [],
        "external_links": [],
    }
    title = _meta_attr(html, "og:title")
    if title and title.strip().lower() not in {"instagram", "instagram.com"}:
        out["display_name"] = title.split("(@")[0].strip() or None
    full_name = _json_str(html, "full_name")
    if full_name:
        out["display_name"] = full_name

    bio = _json_str(html, "biography")
    desc = _meta_attr(html, "og:description", "description")
    if desc:
        out["meta_description"] = desc[:300]
        c = _COUNTS.search(desc)
        if c:
            out["followers"] = _num(c.group(1))
            out["following"] = _num(c.group(2))
            out["posts"] = _num(c.group(3))
            out["followers_source"] = "og_description"
            out["following_source"] = "og_description"
            out["posts_source"] = "og_description"
            out["followers_raw"] = c.group(1).strip()
        elif "followers" in desc.lower() and out.get("followers") is None:
            loose = _COUNTS_LOOSE.search(desc)
            if loose:
                out["followers"] = _num(loose.group(1))
                out["followers_source"] = "og_description"
                out["followers_raw"] = loose.group(1).strip()
        tail = desc.split(" - ", 1)
        if len(tail) == 2 and ":" in tail[1]:
            bio = bio or tail[1].split(":", 1)[1].strip().strip('"') or None
    if bio:
        out["bio"] = bio

    json_followers = _first_int(html, _JSON_FOLLOWERS)
    if json_followers is not None:
        out["followers"] = json_followers
        out["followers_source"] = "json"
        out.pop("followers_raw", None)
    json_following = _first_int(html, _JSON_FOLLOWING)
    if json_following is not None:
        out["following"] = json_following
        out["following_source"] = "json"
    json_posts = _first_int(html, _JSON_POSTS)
    if json_posts is not None:
        out["posts"] = json_posts
        out["posts_source"] = "json"

    if '"is_verified":true' in html or '"isVerified":true' in html:
        out["verified"] = True

    for hl in re.findall(r'"highlight_title"\s*:\s*"([^"]{1,40})"', html)[:20]:
        if hl not in out["highlights"]:
            out["highlights"].append(hl)
    for link in re.findall(r'"external_url"\s*:\s*"([^"]+)"', html)[:5]:
        clean = link.replace("\\/", "/")
        if clean not in out["external_links"]:
            out["external_links"].append(clean)
    return out


def _set_count(acc: PlatformAccount, field: str, value: int | None, source: str | None) -> None:
    if value is None:
        return
    current = getattr(acc, field)
    current_src = acc.raw.get(f"{field}_source")
    incoming_rank = _COUNT_RANK.get(source or "", 0)
    current_rank = _COUNT_RANK.get(current_src or "", 0)
    if current is None or incoming_rank > current_rank:
        setattr(acc, field, value)
        if source:
            acc.raw[f"{field}_source"] = source


def apply_public_html(acc: PlatformAccount, html: str) -> None:
    parsed = parse_public_html(html)
    if parsed.get("display_name") and (
            not acc.display_name or len(parsed["display_name"]) > len(acc.display_name)):
        acc.display_name = parsed["display_name"]
    if parsed.get("bio") and (not acc.bio or len(parsed["bio"]) > len(acc.bio)):
        acc.bio = parsed["bio"]
    if parsed.get("verified"):
        acc.verified = True
    _set_count(acc, "followers", parsed.get("followers"), parsed.get("followers_source"))
    _set_count(acc, "following", parsed.get("following"), parsed.get("following_source"))
    _set_count(acc, "posts", parsed.get("posts"), parsed.get("posts_source"))
    if parsed.get("meta_description"):
        acc.raw["meta_description"] = parsed["meta_description"]
    raw_followers = parsed.get("followers_raw")
    if (parsed.get("followers_source") == "og_description" and acc.followers
            and raw_followers and _suspicious(acc.followers, raw_followers)
            and acc.raw.get("followers_source") == "og_description"):
        acc.raw["followers_precision"] = "rounded"
        acc.errors.append(
            f"Follower count '{raw_followers}' came from Instagram's meta tag, "
            "which rounds heavily and can be stale."
        )
    for hl in parsed.get("highlights") or []:
        if hl not in acc.highlights:
            acc.highlights.append(hl)
    for link in parsed.get("external_links") or []:
        if link not in acc.external_links:
            acc.external_links.append(link)


def _merge_ig(base: PlatformAccount, extra: PlatformAccount) -> None:
    if extra.display_name and (
            not base.display_name or len(extra.display_name) > len(base.display_name)):
        base.display_name = extra.display_name
    if extra.bio and (not base.bio or len(extra.bio) > len(base.bio)):
        base.bio = extra.bio
    if extra.verified:
        base.verified = True
    src = extra.raw.get("source") or extra.raw.get("followers_source")
    _set_count(base, "followers", extra.followers, src)
    _set_count(base, "following", extra.following, src)
    _set_count(base, "posts", extra.posts, src)
    for hl in extra.highlights:
        if hl not in base.highlights:
            base.highlights.append(hl)
    for link in extra.external_links:
        if link not in base.external_links:
            base.external_links.append(link)
    for err in extra.errors:
        if err not in base.errors:
            base.errors.append(err)


async def _via_provider(handle: str) -> PlatformAccount | None:
    if settings.ig_provider != "generic_http" or not settings.ig_provider_url:
        return None
    url = settings.ig_provider_url.replace("{handle}", handle)
    hdrs = {"Authorization": f"Bearer {settings.ig_provider_key}"} if settings.ig_provider_key else {}
    r = await fetch(url, headers=hdrs, check_robots=False, use_cache=True)
    if not r.ok:
        return None
    try:
        d: dict[str, Any] = json.loads(r.text)
    except json.JSONDecodeError:
        return None
    d = d.get("data", d)
    acc = PlatformAccount(
        platform="instagram", handle=handle,
        url=f"https://www.instagram.com/{handle}/",
        display_name=d.get("full_name") or d.get("name"),
        bio=d.get("biography") or d.get("bio"),
        followers=d.get("follower_count") or d.get("followers"),
        following=d.get("following_count") or d.get("following"),
        posts=d.get("media_count") or d.get("posts"),
        verified=d.get("is_verified"),
        raw={"source": "commercial_provider"},
    )
    for p in (d.get("recent_posts") or d.get("posts_data") or [])[:30]:
        acc.content.append(ContentItem(
            platform="instagram",
            title=(p.get("caption") or "")[:180],
            url=p.get("url") or p.get("permalink"),
            views=p.get("view_count") or p.get("play_count"),
            likes=p.get("like_count"), comments=p.get("comment_count"),
            kind=p.get("media_type", "post").lower(),
        ))
    return acc


async def _via_browser(handle: str) -> PlatformAccount | None:
    """Render the public profile header, logged out — what any visitor sees.

    This is how the follower counts, bio, verification badge and highlight names in the
    original hand-made report were obtained. It does not touch the post grid, which
    Instagram puts behind a sign-in prompt.
    """
    if not br.enabled():
        return None
    r = await br.instagram_profile(handle)
    if not r.ok:
        return None
    d = br.parse_instagram(r.text)
    if not any(d.get(k) for k in ("followers", "display_name", "bio")):
        return None
    acc = PlatformAccount(
        platform="instagram", handle=handle,
        url=f"https://www.instagram.com/{handle}/",
        display_name=d.get("display_name"), bio=d.get("bio"),
        followers=d.get("followers"), following=d.get("following"),
        posts=d.get("posts"), verified=d.get("verified") or None,
        highlights=d.get("highlights", [])[:14],
        external_links=d.get("external_links", [])[:5],
        raw={"source": "browser_render"},
    )
    if r.challenged:
        acc.errors.append(r.notes[0] if r.notes else "sign-in prompt encountered")
    # Post-level metrics stay behind the login wall regardless of rendering.
    acc.needs_manual = True
    return acc


async def collect(handle: str) -> PlatformAccount:
    provided = await _via_provider(handle)
    if provided:
        return provided

    url = f"https://www.instagram.com/{handle}/"
    acc = PlatformAccount(platform="instagram", handle=handle, url=url,
                          raw={"source": "public_profile_html"})
    r = await fetch(url, check_robots=False)  # a profile page is the creator's own public page
    if not r.ok:
        acc.errors.append(f"profile fetch returned status {r.status}")
    else:
        apply_public_html(acc, r.text)

    if settings.browser_mode in ("always", "auto") and br.enabled():
        rendered = await _via_browser(handle)
        if rendered:
            _merge_ig(acc, rendered)

    # Post-level and audience data is login-walled. Offer optional enrichment later.
    acc.needs_manual = True
    if acc.followers is None:
        acc.errors.append(_MISSING_FOLLOWERS)
    return acc


MANUAL_FIELDS: list[dict[str, str]] = [
    {"key": "followers", "label": "Followers", "type": "number",
     "help": "From the profile header."},
    {"key": "following", "label": "Following", "type": "number", "help": ""},
    {"key": "posts", "label": "Posts", "type": "number", "help": ""},
    {"key": "verified", "label": "Verified (blue tick)", "type": "checkbox", "help": ""},
    {"key": "bio", "label": "Bio text", "type": "textarea",
     "help": "Paste verbatim, including emoji — the engine reads it for positioning signals."},
    {"key": "highlights", "label": "Story highlight names", "type": "text",
     "help": "Comma-separated, left to right. These are a strong content-pillar signal."},
    {"key": "avg_reel_views", "label": "Average reel views (last 12)", "type": "number",
     "help": "From Insights, or eyeball the grid."},
    {"key": "avg_likes", "label": "Average likes (last 12 posts)", "type": "number", "help": ""},
    {"key": "avg_comments", "label": "Average comments (last 12 posts)", "type": "number", "help": ""},
    {"key": "audience_age", "label": "Audience age split", "type": "text",
     "help": "Only from Insights, e.g. '18-24:41, 25-34:33'. Blank stays unavailable."},
    {"key": "audience_gender", "label": "Audience gender split", "type": "text",
     "help": "e.g. 'male:68, female:32'. Blank stays unavailable."},
    {"key": "audience_cities", "label": "Top cities", "type": "text",
     "help": "Comma-separated, ranked. Blank stays unavailable."},
    {"key": "top_posts", "label": "Best-performing posts", "type": "textarea",
     "help": "One per line: caption or topic | views. Feeds the interest ranking."},
]


def merge_manual(acc: PlatformAccount, manual: dict[str, Any]) -> PlatformAccount:
    """Fold analyst-supplied values in. Manual values always win over scraped ones."""
    if not manual:
        return acc
    for f in ("followers", "following", "posts", "avg_reel_views", "avg_likes", "avg_comments"):
        v = manual.get(f)
        if v in (None, ""):
            continue
        try:
            iv = int(str(v).replace(",", ""))
        except ValueError:
            continue
        if f in ("followers", "following", "posts"):
            setattr(acc, f, iv)
        else:
            acc.raw[f] = iv
    if manual.get("verified") in (True, "true", "on", "1"):
        acc.verified = True
    if manual.get("bio"):
        acc.bio = manual["bio"]
    if manual.get("highlights"):
        acc.highlights = [h.strip() for h in str(manual["highlights"]).split(",") if h.strip()]
    for k in ("audience_age", "audience_gender", "audience_cities"):
        if manual.get(k):
            acc.raw[k] = manual[k]
    if manual.get("top_posts"):
        for line in str(manual["top_posts"]).splitlines():
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split("|")]
            views = None
            if len(parts) > 1:
                try:
                    views = int(re.sub(r"[^\d]", "", parts[1]) or 0) or None
                except ValueError:
                    views = None
            acc.content.append(ContentItem(
                platform="instagram", title=parts[0], views=views, kind="reel",
                raw={"source": "manual"},
            ))
    acc.needs_manual = False
    acc.raw["manual_merged"] = True
    return acc
