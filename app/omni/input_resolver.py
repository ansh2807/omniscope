"""Universal input classification — anything pasted becomes a typed investigation.

Kinds today:

  * ``creator`` — a social profile URL or a bare @handle. Routed to the existing
    creator pipeline (`app.engine.pipeline`).
  * ``website`` — a bare domain or any non-social URL. Routed to the web
    intelligence engine (`app.omni.webintel`).
  * ``keyword`` — free text: a company name, product, topic. Needs a search
    provider to resolve into an entity; degrades honestly without one.
  * ``post`` — a social post or video URL. Public metadata only (HTML + oEmbed).

The existing `app.engine.resolver` stays authoritative for social-platform URL
parsing; this module wraps it rather than duplicating patterns.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.engine.resolver import HANDLE_ONLY, resolve as resolve_social

KIND_CREATOR = "creator"
KIND_WEBSITE = "website"
KIND_KEYWORD = "keyword"
KIND_POST = "post"

# A social *post* or video is not a profile and must not be crawled as a website.
POST_HINT = re.compile(
    r"instagram\.com/(?:p|reel|reels|tv)/|"
    r"youtube\.com/watch|youtu\.be/|"
    r"tiktok\.com/.*/video/|"
    r"(?:twitter|x)\.com/[^/]+/status/|"
    r"linkedin\.com/(?:posts|feed)/|"
    r"facebook\.com/.+/(?:posts|videos)/|"
    r"reddit\.com/r/[^/]+/comments/|"
    r"bsky\.app/profile/[^/]+/post/|"
    r"pinterest\.[^/]+/pin/|"
    r"news\.ycombinator\.com/item",
    re.I)

# A bare token that looks like a registrable domain: at least one dot, a plausible TLD.
DOMAIN_LIKE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}(?:/[^\s]*)?$", re.I)


@dataclass
class UniversalInput:
    kind: str                 # creator | website | keyword
    value: str                # canonical seed: URL for creator/website, text for keyword
    original: str
    platform: str = ""        # creator only
    handle: str = ""          # creator only
    domain: str = ""          # website only
    notes: list[str] = field(default_factory=list)


def classify(raw: str) -> UniversalInput:
    """Decide what kind of investigation this input starts."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("empty input")

    has_scheme = s.startswith(("http://", "https://"))

    # Free text with spaces is never a URL or handle — it is a keyword/entity query.
    if " " in s and not has_scheme:
        return UniversalInput(kind=KIND_KEYWORD, value=s, original=raw)

    # An explicit @handle is always a creator seed.
    if s.startswith("@"):
        r = resolve_social(s)
        return UniversalInput(kind=KIND_CREATOR, value=r.url, original=raw,
                              platform=r.platform, handle=r.handle)

    if POST_HINT.search(s):
        return UniversalInput(
            kind=KIND_POST, value=s if has_scheme else "https://" + s,
            original=raw,
            notes=["post/video URL — public metadata engine"])

    # Social-platform URLs are creator seeds. resolve() falls back to
    # platform="website" for everything it does not recognise. resolve() only adds
    # a scheme to bare handles, so give a bare domain one here or urlparse sees no host.
    if has_scheme or "." in s.split("/")[0]:
        r = resolve_social(s if has_scheme else "https://" + s)
        if r.platform != "website":
            return UniversalInput(kind=KIND_CREATOR, value=r.url, original=raw,
                                  platform=r.platform, handle=r.handle)
        host = urlparse(r.url).netloc.lower().removeprefix("www.")
        if host and DOMAIN_LIKE.match(host):
            return UniversalInput(kind=KIND_WEBSITE, value=r.url, original=raw,
                                  domain=host)
        return UniversalInput(kind=KIND_KEYWORD, value=s, original=raw,
                              notes=["input looked like a URL but has no valid host"])

    # A bare single token without a dot: preserve the existing product behaviour of
    # treating it as a creator handle (default platform Instagram).
    if HANDLE_ONLY.match(s):
        r = resolve_social(s)
        return UniversalInput(kind=KIND_CREATOR, value=r.url, original=raw,
                              platform=r.platform, handle=r.handle)

    return UniversalInput(kind=KIND_KEYWORD, value=s, original=raw)
