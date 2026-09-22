"""Handle probing — find a creator's other platforms without a search API.

The discovery layer's search operators need a paid key. This module does not: it takes
the handle you already have and asks each platform directly whether that handle exists
there, then verifies the result actually belongs to the same person before accepting it.

That is how a human does it. If you know someone is `@democreator` on Instagram, you type
youtube.com/@democreator and look. This automates exactly that, and refuses to record a
hit it cannot verify.

Only platforms that give an honest 404 for a missing handle are probed. Anything behind
an authentication wall (LinkedIn, Facebook) cannot be verified from outside and is
deliberately left alone rather than guessed at.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.engine.http import fetch
from app.engine.numbers import parse_human_count

# Handle variants worth trying. Creators rarely keep punctuation consistent across sites.
def variants(handle: str, display_name: str | None = None) -> list[str]:
    h = (handle or "").strip().lstrip("@")
    out: list[str] = []

    def add(v: str) -> None:
        v = v.strip("._-")
        if v and 2 < len(v) <= 40 and v.lower() not in {x.lower() for x in out}:
            out.append(v)

    add(h)
    add(h.replace(".", ""))
    add(h.replace("_", ""))
    add(h.replace(".", "_"))
    add(h.replace("_", "."))
    add(re.sub(r"(official|_official|\.official)$", "", h, flags=re.I))
    if not h.lower().endswith("official"):
        add(h + "official")
    if display_name:
        slug = re.sub(r"[^a-z0-9]", "", display_name.lower())
        add(slug)
        parts = [p for p in re.split(r"\s+", display_name.lower()) if p.isalpha()]
        if len(parts) >= 2:
            add("".join(parts[:2]))
            add("_".join(parts[:2]))
            add(".".join(parts[:2]))
    return out[:6]


@dataclass
class Probe:
    platform: str
    url: str
    handle: str
    confirmed: bool = False
    confidence: float = 0.0
    evidence: str = ""
    display_name: str | None = None
    followers_hint: int | None = None


@dataclass
class ProbeResult:
    hits: list[Probe] = field(default_factory=list)
    attempted: int = 0
    notes: list[str] = field(default_factory=list)


def _tokens(*vals: str | None) -> set[str]:
    blob = " ".join(v or "" for v in vals).lower()
    return {t for t in re.split(r"[^a-z0-9]+", blob) if len(t) > 2}


def _matches(page_text: str, page_title: str, handle: str,
             name_tokens: set[str]) -> tuple[bool, float, str]:
    """Does this page actually belong to the person we are looking for?"""
    blob = f"{page_title} {page_text[:4000]}".lower()
    h = handle.lower()

    if h in blob.replace(" ", ""):
        return True, 0.9, f"handle '{handle}' appears on the page"
    hits = [t for t in name_tokens if t in blob]
    if len(hits) >= 2:
        return True, 0.75, f"display-name tokens {sorted(hits)[:3]} appear on the page"
    if len(hits) == 1 and len(name_tokens) == 1:
        return True, 0.6, f"display-name token '{hits[0]}' appears on the page"
    return False, 0.0, "page exists but does not identify the same person"


# --------------------------------------------------------------- per-platform
async def _youtube(v: str, name_tokens: set[str]) -> Probe | None:
    url = f"https://www.youtube.com/@{v}"
    r = await fetch(url, check_robots=False)
    if not r.ok or "This page isn't available" in r.text or "404" in r.text[:200]:
        return None
    title = re.search(r"<title>(.*?)</title>", r.text, re.S)
    title_s = title.group(1) if title else ""
    if "404" in title_s or not title_s:
        return None
    ok, conf, why = _matches(r.text, title_s, v, name_tokens)
    subs = None
    m = re.search(r'"subscriberCountText".{0,120}?"simpleText":"([\d.,]+[KMB]?) subscribers?"',
                  r.text)
    if m:
        subs = _num(m.group(1))
    # A handle can be squatted. An account with a handful of subscribers and no video
    # grid is not the channel we are looking for, however well the handle matches.
    videos = r.text.count('"videoRenderer"')
    if ok and subs is not None and subs < 100 and videos == 0:
        ok, conf = False, 0.0
        why = (f"handle matches but the channel has {subs} subscribers and no videos — "
               f"almost certainly a squatted or abandoned account")
    return Probe("youtube", url, v, ok, conf, why,
                 display_name=title_s.replace(" - YouTube", "").strip() or None,
                 followers_hint=subs)


async def _telegram(v: str, name_tokens: set[str]) -> Probe | None:
    url = f"https://t.me/{v}"
    r = await fetch(url, check_robots=False)
    if not r.ok:
        return None
    if "tgme_page_title" not in r.text and "If you have Telegram" not in r.text:
        return None
    title = re.search(r'<meta property="og:title" content="([^"]*)"', r.text)
    title_s = title.group(1) if title else ""
    if not title_s or title_s.lower() in ("telegram", "telegram: contact"):
        return None
    ok, conf, why = _matches(r.text, title_s, v, name_tokens)
    return Probe("telegram", f"https://t.me/s/{v}", v, ok, conf, why, display_name=title_s)


async def _threads(v: str, name_tokens: set[str]) -> Probe | None:
    url = f"https://www.threads.net/@{v}"
    r = await fetch(url, check_robots=False)
    if not r.ok:
        return None
    title = re.search(r'<meta property="og:title" content="([^"]*)"', r.text)
    title_s = title.group(1) if title else ""
    if not title_s or "page not found" in r.text.lower():
        return None
    ok, conf, why = _matches(r.text, title_s, v, name_tokens)
    return Probe("threads", url, v, ok, conf, why, display_name=title_s)


async def _x(v: str, name_tokens: set[str]) -> Probe | None:
    """Probe X via the public syndication follow-button endpoint (no login)."""
    from urllib.parse import quote
    import json as _json

    api = ("https://cdn.syndication.twimg.com/widgets/followbutton/info.json"
           f"?screen_names={quote(v)}")
    r = await fetch(api, check_robots=False, headers={"Accept": "application/json"})
    if not r.ok or not (r.text or "").strip():
        return None
    try:
        data = _json.loads(r.text)
    except Exception:
        return None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    row = data[0]
    screen = (row.get("screen_name") or v).lstrip("@")
    name = row.get("name") or ""
    desc = row.get("description") or ""
    url = f"https://x.com/{screen}"
    ok, conf, why = _matches(f"{name} {desc} @{screen}", name, v, name_tokens)
    # Exact handle match on a live syndication row is strong identity evidence.
    if screen.lower() == v.lower():
        ok, conf = True, max(conf, 0.85)
        why = f"X handle @{screen} resolved on the public syndication endpoint"
    if not ok:
        return None
    subs = None
    try:
        if row.get("followers_count") is not None:
            subs = int(row["followers_count"])
    except (TypeError, ValueError):
        subs = _num(str(row.get("followers_count") or ""))
    return Probe("x", url, screen, ok, conf, why,
                 display_name=name or None, followers_hint=subs)


async def _simple(platform: str, url: str, v: str, name_tokens: set[str],
                  missing_markers: tuple[str, ...]) -> Probe | None:
    r = await fetch(url, check_robots=False)
    if not r.ok:
        return None
    low = r.text.lower()
    if any(m in low for m in missing_markers):
        return None
    title = re.search(r'<meta property="og:title" content="([^"]*)"', r.text) or \
        re.search(r"<title>(.*?)</title>", r.text, re.S)
    title_s = title.group(1).strip() if title else ""
    ok, conf, why = _matches(r.text, title_s, v, name_tokens)
    return Probe(platform, url, v, ok, conf, why, display_name=title_s or None)


def _num(s: str) -> int | None:
    return parse_human_count(s)


PROBERS = {
    "youtube": _youtube,
    "telegram": _telegram,
    "threads": _threads,
    "x": _x,
}
SIMPLE = [
    ("topmate", "https://topmate.io/{v}", ("page not found", "404 |", "not found")),
    ("linktree", "https://linktr.ee/{v}", ("page not found", "sorry, this page")),
    ("superprofile", "https://superprofile.bio/{v}", ("not found", "404")),
]


async def run(handle: str, *, display_name: str | None = None,
              known: set[str] | None = None, max_variants: int = 3) -> ProbeResult:
    """Probe every verifiable platform for this handle. No search API involved."""
    res = ProbeResult()
    known = known or set()
    name_tokens = _tokens(display_name, handle)
    cands = variants(handle, display_name)[:max_variants]

    for platform, prober in PROBERS.items():
        if platform in known:
            continue
        for v in cands:
            res.attempted += 1
            try:
                p = await prober(v, name_tokens)
            except Exception:
                p = None
            if p and p.confirmed:
                res.hits.append(p)
                break

    for platform, tmpl, markers in SIMPLE:
        if platform in known:
            continue
        for v in cands:
            res.attempted += 1
            try:
                p = await _simple(platform, tmpl.format(v=v), v, name_tokens, markers)
            except Exception:
                p = None
            if p and p.confirmed:
                res.hits.append(p)
                break

    if res.hits:
        res.notes.append(
            f"{len(res.hits)} additional platform(s) found by probing the handle directly "
            f"across {res.attempted} checks — no search API was used. Each hit was verified "
            f"by matching the handle or display name on the page itself.")
    else:
        res.notes.append(
            f"Probed {res.attempted} handle variants across YouTube, X, Telegram, Threads, "
            f"Topmate, Linktree and SuperProfile; none could be verified as the same "
            f"person. LinkedIn and Facebook are behind authentication walls and cannot be "
            f"verified from outside, so they are never guessed at.")
    return res
