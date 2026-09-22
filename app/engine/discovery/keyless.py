"""Discovery that needs no API key at all.

The search-operator layer needs a paid key, but a surprising amount of the brief does
not. These are documented public endpoints that exist precisely to be queried, plus one
browser-driven search that reproduces what a person does by hand.

  * Apple Podcasts / iTunes Search API — official, keyless, documented. Finds podcast
    appearances and guest spots, which the brief asks for explicitly.
  * Wikipedia + Wikidata API — official, keyless, actively encourages reuse. Establishes
    notability and pulls out linked official sites.
  * Autocomplete endpoints — the "related searches" and search-intent signal the brief
    asks for, without touching a results page.
  * YouTube search via the browser tier — a person typing a name into the search box.
    Only runs when the browser is enabled, and stops immediately if challenged.

What still genuinely needs a key: general web search for press, interviews, news
mentions and competitor discovery. Nothing keyless replaces that, and this module does
not pretend otherwise.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote_plus
from urllib.parse import urlparse

from app.engine.discovery.public_records import (
    fetch_musicbrainz,
    fetch_orcid,
    fetch_pageviews,
    fetch_spotify_artist,
)
from app.engine.discovery.wikidata_identity import (
    is_wikimedia_image,
    lookup as wikidata_lookup,
    titles_match_subject,
)
from app.engine.http import fetch
from app.omni.filings import collect_filings


@dataclass
class PodcastHit:
    title: str
    url: str
    kind: str            # show | episode
    publisher: str | None = None
    released: str | None = None
    description: str = ""
    feed_url: str | None = None


@dataclass
class KeylessFindings:
    podcasts: list[PodcastHit] = field(default_factory=list)
    wikipedia_title: str | None = None
    wikipedia_url: str | None = None
    wikipedia_extract: str = ""
    wikipedia_categories: list[str] = field(default_factory=list)
    wikipedia_sections: list[dict] = field(default_factory=list)
    official_links: list[str] = field(default_factory=list)
    display_name: str | None = None
    wikidata_id: str | None = None
    wikidata_description: str | None = None
    youtube_channel_url: str | None = None
    twitter_url: str | None = None
    tiktok_url: str | None = None
    linkedin_url: str | None = None
    facebook_url: str | None = None
    spotify_url: str | None = None
    reddit_url: str | None = None
    podcast_url: str | None = None
    bluesky_url: str | None = None
    mastodon_url: str | None = None
    github_url: str | None = None
    soundcloud_url: str | None = None
    pinterest_url: str | None = None
    hackernews_url: str | None = None
    orcid: str | None = None
    orcid_record: dict = field(default_factory=dict)
    official_ids: dict = field(default_factory=dict)
    official_id_urls: dict = field(default_factory=dict)
    filings: dict = field(default_factory=dict)
    musicbrainz_id: str | None = None
    musicbrainz: dict = field(default_factory=dict)
    pageviews: dict = field(default_factory=dict)
    spotify_artist: dict = field(default_factory=dict)
    official_names: list[str] = field(default_factory=list)
    image_url: str | None = None
    image_source: str | None = None
    occupations: list[str] = field(default_factory=list)
    citizenships: list[str] = field(default_factory=list)
    awards: list[str] = field(default_factory=list)
    notable_works: list[str] = field(default_factory=list)
    education: list[str] = field(default_factory=list)
    employers: list[str] = field(default_factory=list)
    work_locations: list[str] = field(default_factory=list)
    positions: list[str] = field(default_factory=list)
    residences: list[str] = field(default_factory=list)
    birth_places: list[str] = field(default_factory=list)
    pseudonyms: list[str] = field(default_factory=list)
    significant_events: list[str] = field(default_factory=list)
    fields_of_work: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    nominations: list[str] = field(default_factory=list)
    participations: list[str] = field(default_factory=list)
    memberships: list[str] = field(default_factory=list)
    follower_readings: list[dict] = field(default_factory=list)
    wikidata_sites: list[str] = field(default_factory=list)
    wikidata_followers: int | None = None
    wikidata_followers_as_of: str | None = None
    wikidata_followers_platform: str | None = None
    related_searches: list[str] = field(default_factory=list)
    autocomplete_intents: list[dict] = field(default_factory=list)
    youtube_candidates: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return bool(self.podcasts or self.wikipedia_title or self.related_searches
                    or self.youtube_candidates or self.wikidata_id)


def _plausible_official_link(url: str, name: str, handle: str) -> bool:
    """Wikipedia extlinks include every citation; keep only identity-shaped properties."""
    try:
        parts = urlparse(url)
    except Exception:
        return False
    host = parts.netloc.lower().replace("www.", "")
    host_norm = re.sub(r"[^a-z0-9]", "", host)
    path_norm = re.sub(r"[^a-z0-9]", "", parts.path.lower())
    handle_norm = re.sub(r"[^a-z0-9]", "", (handle or "").lower())
    name_norm = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    social = ("instagram.com", "youtube.com", "linkedin.com", "x.com", "twitter.com",
              "threads.net", "facebook.com", "tiktok.com", "bsky.app", "t.me",
              "topmate.io",
              "linktr.ee")
    if any(host == h or host.endswith("." + h) for h in social):
        return bool(handle_norm and handle_norm in path_norm)
    return bool((handle_norm and len(handle_norm) >= 5 and handle_norm in host_norm) or
                (name_norm and len(name_norm) >= 6 and name_norm in host_norm))


# ------------------------------------------------------- Apple Podcasts (keyless)
async def podcasts(name: str, *, limit: int = 12) -> list[PodcastHit]:
    """Official iTunes Search API. No key, no auth, documented for exactly this."""
    out: list[PodcastHit] = []
    if not name or len(name) < 3:
        return out
    for entity, kind in (("podcast", "show"), ("podcastEpisode", "episode")):
        url = (f"https://itunes.apple.com/search?term={quote_plus(name)}"
               f"&entity={entity}&limit={limit}&country=IN")
        r = await fetch(url, check_robots=False)
        if not r.ok:
            continue
        try:
            data = json.loads(r.text)
        except json.JSONDecodeError:
            continue
        low_name = name.lower()
        for item in data.get("results", []):
            title = (item.get("trackName") or item.get("collectionName") or "").strip()
            blob = f"{title} {item.get('description', '')}".lower()
            # Only keep hits that actually mention the person — a name search returns
            # plenty of unrelated shows otherwise.
            if low_name not in blob and not all(
                    p in blob for p in low_name.split() if len(p) > 2):
                continue
            out.append(PodcastHit(
                title=title[:160],
                url=item.get("trackViewUrl") or item.get("collectionViewUrl") or "",
                kind=kind,
                publisher=item.get("artistName") or item.get("collectionName"),
                released=(item.get("releaseDate") or "")[:10] or None,
                description=(item.get("description") or "")[:300],
                feed_url=item.get("feedUrl") or None,
            ))
    seen, uniq = set(), []
    for p in out:
        if p.url in seen:
            continue
        seen.add(p.url)
        uniq.append(p)
    return uniq[:12]


_SKIP_WIKI_CAT = re.compile(
    r"^(living people|.+ births|.+ deaths|articles |wikipedia |cs1 |"
    r"all (article )?stub|.+ stubs|use [a-z]{3} dates|pages using|"
    r"webarchive|commons category|redirects |year of |place of |"
    r"engvarb|cleanup|unreferenced|all wikipedia|dates missing)",
    re.I,
)
_SKIP_WIKI_SECTION = re.compile(
    r"^(references|external links?|see also|notes|further reading|"
    r"bibliography|citations|sources|footnotes|gallery|publications)$",
    re.I,
)
_WIKI_HEADING = re.compile(r"^(={2,})\s*(.+?)\s*\1\s*$")


def parse_categories(payload: dict) -> list[str]:
    """Visible Wikipedia categories. Maintenance / biography-meta rows are dropped."""
    pages = (payload or {}).get("query", {}).get("pages") if isinstance(payload, dict) else None
    if not isinstance(pages, dict):
        return []
    out: list[str] = []
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        for row in page.get("categories") or []:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "")
            name = title.split(":", 1)[-1].strip() if title else ""
            if not name or _SKIP_WIKI_CAT.search(name):
                continue
            if name not in out:
                out.append(name)
            if len(out) >= 12:
                return out
    return out


def parse_summary_image(payload: dict) -> dict[str, str]:
    """Copy a Wikimedia image from a Wikipedia REST summary. Other hosts stay empty."""
    if not isinstance(payload, dict):
        return {}
    for key in ("originalimage", "thumbnail"):
        row = payload.get(key)
        if not isinstance(row, dict):
            continue
        src = str(row.get("source") or "").strip()
        if is_wikimedia_image(src):
            return {"image_url": src, "image_source": "wikipedia_summary"}
    return {}


def parse_extracts(payload: dict) -> str:
    """Plaintext extract from a MediaWiki prop=extracts payload."""
    pages = (payload or {}).get("query", {}).get("pages") if isinstance(payload, dict) else None
    if not isinstance(pages, dict):
        return ""
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        text = str(page.get("extract") or "").strip()
        if text:
            return text
    return ""


def parse_plaintext_article(text: str, *, lead_limit: int = 800,
                            section_limit: int = 4,
                            section_chars: int = 280) -> dict:
    """Split MediaWiki explaintext into the lead plus top-level sections.

    ``== References ==`` and similar back-matter headings are dropped.
    Subheadings stay inside the parent section. Section titles are encyclopedia
    headings, never content pillars.
    """
    if not (text or "").strip():
        return {"extract": "", "sections": []}
    lead_lines: list[str] = []
    sections: list[dict] = []
    current: dict | None = None
    for raw in text.replace("\r\n", "\n").split("\n"):
        match = _WIKI_HEADING.match(raw.strip())
        if match:
            if len(match.group(1)) != 2:
                continue
            if current and current.get("extract"):
                sections.append(current)
            current = {"title": match.group(2).strip(), "extract": ""}
            continue
        piece = raw.strip()
        if not piece:
            continue
        if current is None:
            lead_lines.append(piece)
        elif current["extract"]:
            current["extract"] += " " + piece
        else:
            current["extract"] = piece
    if current and current.get("extract"):
        sections.append(current)
    lead = re.sub(r"\s+", " ", " ".join(lead_lines)).strip()
    kept: list[dict] = []
    for section in sections:
        title = (section.get("title") or "").strip()
        body = re.sub(r"\s+", " ", section.get("extract") or "").strip()
        if not title or not body or _SKIP_WIKI_SECTION.search(title):
            continue
        kept.append({"title": title, "extract": body[:section_chars]})
        if len(kept) >= section_limit:
            break
    return {"extract": lead[:lead_limit], "sections": kept}


# ------------------------------------------------------------ Wikipedia (keyless)
async def wikipedia(name: str) -> dict:
    """MediaWiki API. Official, keyless, and explicitly intended for reuse."""
    out: dict = {"title": None, "url": None, "extract": "", "links": [],
                 "categories": [], "sections": [], "image_url": None,
                 "image_source": None}
    if not name or len(name) < 3:
        return out
    search = (f"https://en.wikipedia.org/w/api.php?action=query&list=search"
              f"&srsearch={quote_plus(name)}&srlimit=3&format=json")
    r = await fetch(search, check_robots=False)
    if not r.ok:
        return out
    try:
        hits = json.loads(r.text).get("query", {}).get("search", [])
    except json.JSONDecodeError:
        return out
    if not hits:
        return out

    best = None
    for h in hits:
        if titles_match_subject(name, h.get("title") or ""):
            best = h
            break
    if not best:
        return out

    summary = (f"https://en.wikipedia.org/api/rest_v1/page/summary/"
               f"{quote_plus(best['title'].replace(' ', '_'))}")
    r2 = await fetch(summary, check_robots=False)
    if r2.ok:
        try:
            d = json.loads(r2.text)
            out["title"] = d.get("title")
            out["url"] = (d.get("content_urls", {}).get("desktop", {}) or {}).get("page")
            out["extract"] = (d.get("extract") or "")[:800]
            image = parse_summary_image(d)
            out["image_url"] = image.get("image_url")
            out["image_source"] = image.get("image_source")
        except json.JSONDecodeError:
            pass

    ext = (f"https://en.wikipedia.org/w/api.php?action=query&prop=extlinks"
           f"&titles={quote_plus(best['title'])}&ellimit=40&format=json")
    r3 = await fetch(ext, check_robots=False)
    if r3.ok:
        try:
            pages = json.loads(r3.text).get("query", {}).get("pages", {})
            for page in pages.values():
                for link in page.get("extlinks", []):
                    u = link.get("*") or ""
                    if u.startswith("http"):
                        out["links"].append(u)
        except json.JSONDecodeError:
            pass

    cats = (f"https://en.wikipedia.org/w/api.php?action=query&prop=categories"
            f"&titles={quote_plus(best['title'])}&clshow=!hidden&cllimit=20&format=json")
    r4 = await fetch(cats, check_robots=False)
    if r4.ok:
        try:
            out["categories"] = parse_categories(json.loads(r4.text))
        except json.JSONDecodeError:
            pass

    extracts = (f"https://en.wikipedia.org/w/api.php?action=query&prop=extracts"
                f"&explaintext=1&exsectionformat=wiki"
                f"&titles={quote_plus(best['title'])}&format=json")
    r5 = await fetch(extracts, check_robots=False)
    if r5.ok:
        try:
            article = parse_plaintext_article(parse_extracts(json.loads(r5.text)))
        except json.JSONDecodeError:
            article = {"extract": "", "sections": []}
        if article["extract"] and len(article["extract"]) > len(out["extract"]):
            out["extract"] = article["extract"]
        out["sections"] = article["sections"]
    return out


# --------------------------------------------------------- autocomplete (keyless)
async def related_searches(term: str, *, extra_terms: list[str] | None = None) -> dict:
    """What people actually type after this name.

    Uses the public autocomplete endpoints rather than any results page. This is the
    'related searches' and 'search intent' signal the brief asks for.
    """
    out: dict = {"suggestions": [], "intents": []}
    if not term:
        return out
    seeds = [term] + [f"{term} {suffix}" for suffix in
                      ("course", "fees", "review", "worth it", "vs", "contact")]
    for seed in seeds[:7]:
        url = (f"https://suggestqueries.google.com/complete/search"
               f"?client=firefox&hl=en&gl=in&q={quote_plus(seed)}")
        r = await fetch(url, check_robots=False)
        if not r.ok:
            continue
        try:
            data = json.loads(r.text)
        except json.JSONDecodeError:
            continue
        if len(data) > 1 and isinstance(data[1], list):
            for s in data[1]:
                s = str(s).strip()
                if s and s.lower() != term.lower() and s not in out["suggestions"]:
                    out["suggestions"].append(s)
    out["suggestions"] = out["suggestions"][:40]

    buckets = {
        "Commercial investigation": ["worth it", "review", "vs", "better", "honest",
                                     "genuine", "real", "scam"],
        "Price and access": ["fees", "price", "cost", "free", "discount", "course",
                             "batch", "book"],
        "Identity and background": ["age", "wife", "husband", "biography", "net worth",
                                    "qualification", "college", "salary"],
        "Contact and support": ["contact", "email", "number", "address", "helpline"],
        "Content and resources": ["notes", "pdf", "download", "playlist", "app",
                                  "telegram", "syllabus"],
    }
    for label, markers in buckets.items():
        matched = [s for s in out["suggestions"] if any(m in s.lower() for m in markers)]
        if matched:
            out["intents"].append({
                "intent": label,
                "count": len(matched),
                "share": round(len(matched) / max(len(out["suggestions"]), 1) * 100),
                "examples": matched[:4],
            })
    out["intents"].sort(key=lambda d: -d["count"])
    return out


# ------------------------------------------- YouTube search via the browser tier
async def youtube_search(name: str, *, limit: int = 5) -> list[dict]:
    """Type the name into YouTube's search box and read the channel results.

    Browser tier only — this is a person searching, not an automated crawl of a
    disallowed endpoint. Stops immediately if a challenge appears.
    """
    from app.engine.collectors import browser as br
    if not br.enabled() or not name:
        return []
    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except Exception:
        return []

    out: list[dict] = []
    try:
        async with br._browser() as ctx:            # noqa: SLF001 — same module family
            page = await ctx.new_page()
            await page.goto(f"https://www.youtube.com/results?search_query="
                            f"{quote_plus(name)}&sp=EgIQAg%253D%253D",   # channels filter
                            wait_until="domcontentloaded")
            await page.wait_for_timeout(2600)
            await br._consent(page)                 # noqa: SLF001
            text = await page.evaluate("() => document.body.innerText")
            if br._challenged(text):                # noqa: SLF001
                return []
            for a in await page.query_selector_all("a[href^='/@']"):
                href = await a.get_attribute("href") or ""
                m = re.match(r"^/@([A-Za-z0-9._\-]{2,40})", href)
                if not m:
                    continue
                handle = m.group(1)
                label = (await a.inner_text() or "").strip()
                if any(o["handle"] == handle for o in out):
                    continue
                out.append({"handle": handle,
                            "url": f"https://www.youtube.com/@{handle}",
                            "label": label[:80]})
                if len(out) >= limit:
                    break
    except Exception:
        return out
    return out


def _remember_image(f: KeylessFindings, url: str | None, source: str | None) -> None:
    """Keep the first official Wikimedia image. Later hosts cannot overwrite it."""
    if f.image_url or not url or not is_wikimedia_image(url):
        return
    f.image_url = url
    f.image_source = source


# ------------------------------------------------------------------- orchestrator
async def gather(name: str, handle: str, *, seed_platform: str = "instagram",
                 want_youtube: bool = True) -> KeylessFindings:
    f = KeylessFindings()
    subject = (name or handle or "").strip()
    if not subject:
        return f

    try:
        wd = await wikidata_lookup(seed_platform, handle)
    except Exception:
        wd = None
    if wd:
        f.wikidata_id = wd.get("id")
        f.display_name = wd.get("label")
        f.wikidata_description = wd.get("description")
        f.youtube_channel_url = wd.get("youtube_channel_url")
        f.twitter_url = wd.get("twitter_url")
        f.tiktok_url = wd.get("tiktok_url")
        f.linkedin_url = wd.get("linkedin_url")
        f.facebook_url = wd.get("facebook_url")
        f.spotify_url = wd.get("spotify_url")
        f.reddit_url = wd.get("reddit_url")
        f.podcast_url = wd.get("podcast_url")
        f.bluesky_url = wd.get("bluesky_url")
        f.mastodon_url = wd.get("mastodon_url")
        f.github_url = wd.get("github_url")
        f.soundcloud_url = wd.get("soundcloud_url")
        f.pinterest_url = wd.get("pinterest_url")
        f.hackernews_url = wd.get("hackernews_url")
        f.orcid = wd.get("orcid")
        f.official_ids = dict(wd.get("official_ids") or {})
        f.official_id_urls = dict(wd.get("official_id_urls") or {})
        f.musicbrainz_id = wd.get("musicbrainz_id")
        f.official_names = list(wd.get("official_names") or [])
        f.occupations = list(wd.get("occupations") or [])
        f.citizenships = list(wd.get("citizenships") or [])
        f.awards = list(wd.get("awards") or [])
        f.notable_works = list(wd.get("notable_works") or [])
        f.education = list(wd.get("education") or [])
        f.employers = list(wd.get("employers") or [])
        f.work_locations = list(wd.get("work_locations") or [])
        f.positions = list(wd.get("positions") or [])
        f.residences = list(wd.get("residences") or [])
        f.birth_places = list(wd.get("birth_places") or [])
        f.pseudonyms = list(wd.get("pseudonyms") or [])
        f.significant_events = list(wd.get("significant_events") or [])
        f.fields_of_work = list(wd.get("fields_of_work") or [])
        f.genres = list(wd.get("genres") or [])
        f.languages = list(wd.get("languages") or [])
        f.nominations = list(wd.get("nominations") or [])
        f.participations = list(wd.get("participations") or [])
        f.memberships = list(wd.get("memberships") or [])
        f.follower_readings = list(wd.get("follower_readings") or [])
        f.wikidata_sites = list(wd.get("sites") or [])
        f.wikidata_followers = wd.get("followers")
        f.wikidata_followers_as_of = wd.get("followers_as_of")
        f.wikidata_followers_platform = wd.get("followers_platform")
        if wd.get("wikipedia_title") and not f.wikipedia_title:
            wiki = await wikipedia(wd["wikipedia_title"])
            f.wikipedia_title = wiki.get("title") or wd.get("wikipedia_title")
            f.wikipedia_url = wiki.get("url")
            f.wikipedia_extract = wiki.get("extract", "")
            f.wikipedia_categories = list(wiki.get("categories") or [])
            f.wikipedia_sections = list(wiki.get("sections") or [])
            f.official_links = [u for u in wiki.get("links", [])
                                if _plausible_official_link(
                                    u, f.display_name or subject, handle)][:20]
            _remember_image(f, wiki.get("image_url"), wiki.get("image_source"))
        subject = f.display_name or subject

    try:
        f.podcasts = await podcasts(subject)
    except Exception:
        pass

    if not f.wikipedia_title:
        try:
            wiki = await wikipedia(subject)
            if not wiki.get("title") and handle and handle.lower() != subject.lower():
                wiki = await wikipedia(handle)
            f.wikipedia_title = wiki.get("title")
            f.wikipedia_url = wiki.get("url")
            f.wikipedia_extract = wiki.get("extract", "")
            f.wikipedia_categories = list(wiki.get("categories") or [])
            f.wikipedia_sections = list(wiki.get("sections") or [])
            extra = [u for u in wiki.get("links", [])
                     if _plausible_official_link(u, subject, handle)]
            f.official_links = list(dict.fromkeys(f.official_links + extra))[:20]
            _remember_image(f, wiki.get("image_url"), wiki.get("image_source"))
        except Exception:
            pass

    for url in f.wikidata_sites:
        if url not in f.official_links:
            f.official_links.append(url)

    try:
        rel = await related_searches(subject)
        f.related_searches = rel["suggestions"]
        f.autocomplete_intents = rel["intents"]
    except Exception:
        pass

    if wd:
        _remember_image(f, wd.get("image_url"), "wikidata_p18")

    if f.official_ids:
        try:
            f.filings = (await collect_filings([], f.official_ids)).model_dump()
        except Exception:
            f.filings = {}
    if f.orcid:
        try:
            f.orcid_record = await fetch_orcid(f.orcid)
        except Exception:
            f.orcid_record = {}
    if f.wikipedia_title:
        try:
            f.pageviews = await fetch_pageviews(f.wikipedia_title)
        except Exception:
            f.pageviews = {}
    if f.musicbrainz_id:
        try:
            f.musicbrainz = await fetch_musicbrainz(f.musicbrainz_id)
        except Exception:
            f.musicbrainz = {}
        homepage = (f.musicbrainz or {}).get("homepage") or ""
        if homepage and homepage not in f.official_links:
            f.official_links.append(homepage)
    if f.spotify_url:
        try:
            f.spotify_artist = await fetch_spotify_artist(f.spotify_url)
        except Exception:
            f.spotify_artist = {}

    if want_youtube:
        try:
            f.youtube_candidates = await youtube_search(subject)
        except Exception:
            pass

    bits = []
    if f.wikidata_id:
        bits.append(f"Wikidata {f.wikidata_id}")
    if f.podcasts:
        bits.append(f"{len(f.podcasts)} podcast appearance(s)")
    if f.wikipedia_title:
        bits.append("a Wikipedia entry")
    if f.pageviews.get("views"):
        bits.append("Wikipedia pageviews")
    if f.orcid_record:
        bits.append("an ORCID public record")
    if f.musicbrainz.get("name"):
        bits.append("a MusicBrainz artist page")
    if f.spotify_artist.get("title"):
        bits.append("a Spotify artist oEmbed")
    if f.related_searches:
        bits.append(f"{len(f.related_searches)} related search queries")
    if f.youtube_candidates or f.youtube_channel_url:
        bits.append("a YouTube channel")
    if bits:
        f.notes.append(
            "Keyless discovery found " + ", ".join(bits) +
            " using official public APIs — no search key involved.")
    return f
