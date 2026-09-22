"""The verification gate.

Nothing gets recorded as belonging to the subject unless it earns it. A creator profile
that lists a stranger's LinkedIn is worse than one that lists nothing, because the reader
cannot tell which rows to trust.

Five ways a surface can qualify:

  1. **Owned link** — the creator linked to it themselves from a page we already trust
     (their bio, their link-in-bio page, their website footer). Highest trust; no further
     proof needed.
  2. **Verified probe** — we guessed the URL from the handle and then confirmed the page
     identifies the same person, by handle or by display-name tokens.
  3. **Cross-source search + page evidence** — a licensed search result matches the
     identity and the collected page independently carries the same name or handle.
  4. **Strong indexed profile identity** — for a login-walled network only, a direct
     profile result has a high identity score from its URL, title and snippet. This
     attributes the surface but never manufactures metrics hidden behind the wall.

  5. **Wikidata identity** — the same Wikidata item that claims the seed handle
     also claims this surface (P2397 / P2002 / P856). Labelled Wikidata, never
     treated as an owned link the creator published themselves.

Anything else is dropped, or kept only as an explicitly-labelled unverified candidate. A
bare domain with no profile path is always junk.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.engine.collectors.github import RESERVED as GITHUB_RESERVED
from app.engine.collectors.pinterest import RESERVED as PINTEREST_RESERVED
from app.engine.collectors.soundcloud import RESERVED as SOUNDCLOUD_RESERVED

# Platforms whose public pages cannot be read from outside. We may still record the URL
# if the creator linked to it themselves, but we must never guess one.
AUTH_WALLED = {"linkedin", "facebook", "whatsapp"}
INDEX_IDENTITY_PLATFORMS = {"linkedin", "x", "threads", "facebook"}

# A URL must have a real profile path, not just a domain.
MIN_PATH = {
    "instagram": r"^/[A-Za-z0-9._]{2,40}/?$",
    "youtube": r"^/(@[A-Za-z0-9._\-]{2,40}|channel/UC[A-Za-z0-9_\-]{20,}|c/[A-Za-z0-9._\-]+)",
    "linkedin": r"^/in/[A-Za-z0-9\-_%]{3,}",
    "x": r"^/[A-Za-z0-9_]{2,15}/?$",
    "threads": r"^/@[A-Za-z0-9._]{2,40}/?$",
    "facebook": r"^/[A-Za-z0-9._\-]{3,}/?$",
    "tiktok": r"^/@[A-Za-z0-9._]{2,40}/?$",
    "reddit": r"^/(?:user|u)/[A-Za-z0-9_\-]{2,}/?$",
    "bluesky": r"^/profile/[^/]+/?$",
    "mastodon": r"^/(@[A-Za-z0-9_\.]{1,30}|users/[A-Za-z0-9_\.]{1,30})/?$",
    "github": r"^/[A-Za-z0-9](?:[A-Za-z0-9\-]{0,37}[A-Za-z0-9])?/?$",
    "soundcloud": r"^/[A-Za-z0-9][A-Za-z0-9_-]{1,24}/?$",
    "pinterest": r"^/[A-Za-z0-9][A-Za-z0-9._-]{2,29}/?$",
    "hackernews": r"news\.ycombinator\.com/user\?id=[A-Za-z0-9_\-]{2,15}",
    "telegram": r"^/(s/)?[A-Za-z0-9_]{4,}",
    "topmate": r"^/[A-Za-z0-9._\-]{3,}",
    "superprofile": r"^/(bookings/)?[A-Za-z0-9._\-]{3,}",
    "linktree": r"^/[A-Za-z0-9._\-]{2,}",
    "appstore": r"/id\d{6,}",
    "playstore": r"[?&]id=[A-Za-z0-9._]+",
    "podcast": r"/(id\d{6,}|show/[A-Za-z0-9]+|podcast/)",
}

GENERIC_PATHS = {"", "/", "/home", "/about", "/explore", "/store", "/apps", "/podcasts",
                 "/store/apps", "/search", "/login", "/signup"}


@dataclass
class Verdict:
    accept: bool
    confidence: float
    reason: str
    source: str = ""          # owned_link | probe | content | wikidata | rejected


def _tokens(*vals: str | None) -> set[str]:
    blob = " ".join(v or "" for v in vals).lower()
    return {t for t in re.split(r"[^a-z0-9]+", blob) if len(t) > 2}


def is_real_profile_url(platform: str, url: str) -> bool:
    """Reject bare domains and section pages — 'play.google.com' is not a profile."""
    try:
        parts = urlparse(url)
    except Exception:
        return False
    path = (parts.path or "").rstrip("/")
    if not parts.netloc:
        return False
    if path.lower() in GENERIC_PATHS:
        return False
    if platform == "github" and path.lstrip("/").lower() in GITHUB_RESERVED:
        return False
    if platform == "soundcloud" and path.lstrip("/").lower() in SOUNDCLOUD_RESERVED:
        return False
    if platform == "pinterest" and path.lstrip("/").lower() in PINTEREST_RESERVED:
        return False
    if platform == "hackernews" and "item" in path.lower():
        return False
    pattern = MIN_PATH.get(platform)
    if not pattern:
        return bool(path and len(path) > 1)
    target = url if platform in ("playstore", "appstore", "podcast", "hackernews") else (path or "/")
    return bool(re.search(pattern, target))


def from_wikidata(platform: str, url: str) -> Verdict:
    """Accept a surface Wikidata already tied to the seed handle."""
    if platform != "website" and not is_real_profile_url(platform, url):
        return Verdict(False, 0.0,
                       f"Rejected: '{url}' is a bare domain or section page, not a profile.",
                       "rejected")
    return Verdict(
        True, 0.88,
        "Accepted: Wikidata records this handle on the same item as this surface.",
        "wikidata",
    )


def plausible_scale(platform: str, followers: int | None, items: int,
                    primary_followers: int | None) -> tuple[bool, str]:
    """A 3-member Telegram channel does not belong to a 9.6M-follower creator.

    Small secondary accounts are normal — but an account with essentially no audience
    AND no content, attached to a subject with a large following, is almost always a
    different person who happens to hold the same handle.
    """
    if followers is None and items == 0:
        return True, ""            # nothing to judge on; handled by other gates
    if not primary_followers or primary_followers < 50_000:
        return True, ""            # no strong prior to compare against
    tiny = (followers is not None and followers < 50) and items == 0
    if tiny:
        return False, (
            f"Rejected: this {platform} account has {followers} followers and no content, "
            f"against a subject with {primary_followers:,} elsewhere. Almost certainly a "
            f"different person holding the same handle.")
    return True, ""


def check(*, platform: str, url: str, from_owned_link: bool,
          probe_confirmed: bool, probe_confidence: float,
          search_confirmed: bool = False, search_confidence: float = 0.0,
          indexed_identity_match: bool = False,
          page_title: str | None = None, page_text: str | None = None,
          subject_handle: str = "", subject_name: str | None = None,
          followers: int | None = None, items: int = 0,
          primary_followers: int | None = None) -> Verdict:
    """The single decision point. Every discovered surface passes through here."""

    if not is_real_profile_url(platform, url):
        return Verdict(False, 0.0,
                       f"Rejected: '{url}' is a bare domain or section page, not a profile.",
                       "rejected")

    ok, why = plausible_scale(platform, followers, items, primary_followers)
    if not ok:
        return Verdict(False, 0.0, why, "rejected")

    if from_owned_link:
        return Verdict(True, 0.95,
                       "Accepted: the creator links to this from their own page.",
                       "owned_link")

    if probe_confirmed and probe_confidence >= 0.6:
        return Verdict(True, probe_confidence,
                       f"Accepted: handle probe verified the identity "
                       f"({probe_confidence:.0%} confidence).", "probe")

    if (platform in INDEX_IDENTITY_PLATFORMS and indexed_identity_match and
            search_confirmed and search_confidence >= 0.90):
        return Verdict(
            True, min(0.93, search_confidence),
            ("Accepted: a direct profile search result matched the subject identity "
             f"at {search_confidence:.0%}; unavailable page metrics remain withheld."),
            "search_identity",
        )

    if platform in AUTH_WALLED:
        return Verdict(False, 0.0,
                       f"Rejected: {platform} is behind an authentication wall, so this "
                       f"URL cannot be verified as the subject's. Guessing it would risk "
                       f"attributing a stranger's profile to them.", "rejected")

    page_match = 0.0
    page_reason = ""
    if page_title or page_text:
        tokens = _tokens(subject_name, subject_handle)
        blob = f"{page_title or ''} {(page_text or '')[:3000]}".lower()
        if subject_handle and subject_handle.lower() in blob.replace(" ", ""):
            page_match = 0.85
            page_reason = "the subject's handle appears on the collected page"
        matched = [t for t in tokens if t in blob]
        if len(matched) >= 2 and page_match < 0.7:
            page_match = 0.7
            page_reason = f"name tokens {sorted(matched)[:3]} appear on the collected page"

    if page_match and search_confirmed and search_confidence >= 0.68:
        confidence = min(0.94, 0.45 * page_match + 0.55 * search_confidence + 0.08)
        return Verdict(True, confidence,
                       f"Accepted: independent search evidence and {page_reason}.",
                       "search+content")

    if page_match >= 0.85:
        return Verdict(True, page_match,
                       f"Accepted: {page_reason}.", "content")

    # Audience size is only a consistency check. It can never establish identity:
    # popular strangers and namesakes are exactly the false positives we must avoid.

    return Verdict(False, 0.0,
                   "Rejected: could not verify this belongs to the subject.", "rejected")
