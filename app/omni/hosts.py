"""Host helpers: retries, typo hints, and public error copy.

Known-host hints are spelling help only. They do not fetch a different site
until the user submits that URL.
"""
from __future__ import annotations

from urllib.parse import urlparse

KNOWN_HOSTS = (
    "pornhub.com",
    "xvideos.com",
    "xhamster.com",
    "onlyfans.com",
    "youtube.com",
    "instagram.com",
    "tiktok.com",
    "reddit.com",
    "wikipedia.org",
    "linkedin.com",
    "x.com",
    "twitter.com",
    "facebook.com",
)

# Edit distance 3+ spellings that still clearly mean a known host.
TYPO_ALIASES = {
    "punchub.com": "pornhub.com",
    "punchhub.com": "pornhub.com",
    "pornhb.com": "pornhub.com",
    "porhub.com": "pornhub.com",
}


def bare_host(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    host = urlparse(raw).netloc.lower() or urlparse(raw).path.split("/")[0].lower()
    return host.removeprefix("www.")


def _levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    prev = list(range(len(right) + 1))
    for i, lch in enumerate(left, start=1):
        curr = [i]
        for j, rch in enumerate(right, start=1):
            ins = curr[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (lch != rch)
            curr.append(min(ins, delete, sub))
        prev = curr
    return prev[-1]


def suggest_host(host: str) -> str:
    """Closest well-known host within edit distance 2, else empty."""
    needle = (host or "").lower().removeprefix("www.")
    if not needle or needle in KNOWN_HOSTS:
        return ""
    if needle in TYPO_ALIASES:
        return TYPO_ALIASES[needle]
    best, dist = "", 99
    for known in KNOWN_HOSTS:
        gap = _levenshtein(needle, known)
        if gap < dist:
            best, dist = known, gap
    return best if 0 < dist <= 2 else ""


def homepage_candidates(url: str) -> list[str]:
    """https/http × apex/www. First success wins; order prefers https + as-typed."""
    raw = (url or "").strip()
    if not raw:
        return []
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parts = urlparse(raw)
    host = (parts.netloc or "").lower()
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    if not host:
        return [raw]
    apex = host.removeprefix("www.")
    hosts = [host]
    alt = f"www.{apex}" if not host.startswith("www.") else apex
    if alt not in hosts:
        hosts.append(alt)
    out: list[str] = []
    for scheme in ("https", "http"):
        for item in hosts:
            candidate = f"{scheme}://{item}{path}{query}"
            if candidate not in out:
                out.append(candidate)
    return out


def fetch_failure_copy(host: str, error: str, *, robots: bool = False) -> str:
    hint = suggest_host(host)
    if robots:
        msg = (f"{host} disallows this crawler in robots.txt, so the site was "
               "not fetched. Wikipedia, news and other keyless sources may still run.")
    elif "did not resolve" in error or "unsafe URL" in error:
        msg = f"{host} did not resolve. Check the spelling."
    elif "ConnectError" in error or "ConnectTimeout" in error or "timeout" in error.lower():
        msg = f"Could not open {host} (connection failed)."
    else:
        msg = f"Homepage fetch failed for {host}."
        if error:
            msg += f" {error[:180]}"
    if hint:
        msg += f" Did you mean {hint}?"
    return msg
