"""Turn whatever the user pasted into a platform + handle we can act on."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.engine.collectors.mastodon import parse_acct as parse_mastodon_acct

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("instagram", re.compile(r"instagram\.com/(?!p/|reel/|reels/|stories/)([A-Za-z0-9._]+)")),
    ("youtube",   re.compile(r"youtube\.com/@([A-Za-z0-9._\-]+)")),
    ("youtube",   re.compile(r"youtube\.com/channel/(UC[A-Za-z0-9_\-]{20,})")),
    ("youtube",   re.compile(r"youtube\.com/c/([A-Za-z0-9._\-]+)")),
    ("linkedin",  re.compile(r"linkedin\.com/in/([A-Za-z0-9\-_%]+)")),
    ("x",         re.compile(r"(?:twitter|x)\.com/([A-Za-z0-9_]+)")),
    ("threads",   re.compile(r"threads\.(?:net|com)/@([A-Za-z0-9._]+)")),
    ("facebook",  re.compile(r"facebook\.com/([A-Za-z0-9._\-]+)")),
    ("tiktok",    re.compile(r"tiktok\.com/@([A-Za-z0-9._]+)")),
    ("reddit",    re.compile(r"reddit\.com/(?:user|u)/([A-Za-z0-9_\-]{2,})")),
    ("bluesky",   re.compile(r"bsky\.app/profile/([^/?#]+)")),
    ("podcast",   re.compile(r"podcasts\.apple\.com/.*id(\d{6,})")),
    ("podcast",   re.compile(r"open\.spotify\.com/show/([A-Za-z0-9]{22})")),
    ("telegram",  re.compile(r"t\.me/(?:s/)?([A-Za-z0-9_]+)")),
    ("topmate",   re.compile(r"topmate\.io/([A-Za-z0-9._\-]+)")),
    ("superprofile", re.compile(r"superprofile\.bio/(?:bookings/)?([A-Za-z0-9._\-]+)")),
    ("linktree",  re.compile(r"linktr\.ee/([A-Za-z0-9._\-]+)")),
    ("appstore",  re.compile(r"apps\.apple\.com/.*/id(\d+)")),
    ("playstore", re.compile(r"play\.google\.com/store/apps/details\?id=([A-Za-z0-9._]+)")),
    ("github",    re.compile(
        r"github\.com/(?!pricing|features|explore|marketplace|topics|login|signup|about|enterprise|security|sponsors|orgs|organizations|settings)([A-Za-z0-9](?:[A-Za-z0-9\-]{0,37}[A-Za-z0-9])?)/?$")),
    ("soundcloud", re.compile(
        r"soundcloud\.com/(?!discover|upload|you|search|stream|charts|pages|terms|signin|signup|login|about)([A-Za-z0-9][A-Za-z0-9_-]{1,24})/?$")),
    ("pinterest", re.compile(
        r"pinterest\.(?:com|[a-z]{2}(?:\.[a-z]{2})?)/(?!pin/|ideas/|today/|search/|login|signup|settings|business|shop/)([A-Za-z0-9][A-Za-z0-9._-]{2,29})/?$")),
    ("hackernews", re.compile(
        r"news\.ycombinator\.com/user\?id=([A-Za-z0-9_\-]{2,15})")),
]

HANDLE_ONLY = re.compile(r"^@?([A-Za-z0-9._]{2,40})$")


@dataclass
class Resolved:
    platform: str
    handle: str
    url: str
    original: str


def resolve(raw: str, default_platform: str = "instagram") -> Resolved:
    """Accepts a full URL, a bare handle, or '@handle'."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("empty input")

    user, instance = parse_mastodon_acct(s, loose=False)
    if user and instance:
        handle = f"{user}@{instance}"
        return Resolved("mastodon", handle, f"https://{instance}/@{user}", raw)

    if not s.startswith(("http://", "https://")) and "." not in s.split("/")[0]:
        m = HANDLE_ONLY.match(s)
        if m:
            handle = m.group(1)
            url = _canonical_url(default_platform, handle)
            return Resolved(default_platform, handle, url, raw)
        s = "https://" + s

    user, instance = parse_mastodon_acct(s, loose=False)
    if user and instance:
        handle = f"{user}@{instance}"
        return Resolved("mastodon", handle, f"https://{instance}/@{user}", raw)

    for platform, pat in PATTERNS:
        m = pat.search(s)
        if m:
            handle = m.group(1)
            return Resolved(platform, handle, _canonical_url(platform, handle), raw)

    host = urlparse(s).netloc
    return Resolved("website", host, s, raw)


def _canonical_url(platform: str, handle: str) -> str:
    return {
        "instagram": f"https://www.instagram.com/{handle}/",
        "youtube": (f"https://www.youtube.com/channel/{handle}"
                    if handle.startswith("UC") else f"https://www.youtube.com/@{handle}"),
        "linkedin": f"https://www.linkedin.com/in/{handle}/",
        "x": f"https://x.com/{handle}",
        "threads": f"https://www.threads.net/@{handle}",
        "facebook": f"https://www.facebook.com/{handle}/",
        "tiktok": f"https://www.tiktok.com/@{handle}",
        "reddit": f"https://www.reddit.com/user/{handle}",
        "bluesky": f"https://bsky.app/profile/{handle}",
        "mastodon": (f"https://{handle.split('@', 1)[1]}/@{handle.split('@', 1)[0]}"
                     if "@" in handle else handle),
        "podcast": (f"https://podcasts.apple.com/podcast/id{handle}"
                    if handle.isdigit() else f"https://open.spotify.com/show/{handle}"),
        "telegram": f"https://t.me/s/{handle}",
        "topmate": f"https://topmate.io/{handle}",
        "superprofile": f"https://superprofile.bio/{handle}",
        "github": f"https://github.com/{handle}",
        "soundcloud": f"https://soundcloud.com/{handle}",
        "pinterest": f"https://www.pinterest.com/{handle}/",
        "hackernews": f"https://news.ycombinator.com/user?id={handle}",
        "linktree": f"https://linktr.ee/{handle}",
        "appstore": f"https://apps.apple.com/us/app/id{handle}",
        "playstore": f"https://play.google.com/store/apps/details?id={handle}",
    }.get(platform, handle)
