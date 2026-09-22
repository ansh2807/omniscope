"""YouTube collector.

Primary path: YouTube Data API v3 (set YOUTUBE_API_KEY). A latest-plus-popular report
costs roughly 104 quota units because ``search.list`` costs 100 units; the remaining
channel, uploads-playlist and video-detail calls cost about one unit each. It gives exact
subscriber counts, per-video view counts and publish dates.

Fallback path: parse `ytInitialData` out of the public channel page. No auth, no
credentials, nothing hidden — the same JSON the page itself renders from. Used when
no API key is configured. Slightly less precise (subscriber counts are rounded, e.g.
"1.01M") but perfectly usable.

Last resort: YouTube's public Atom feed
(``/feeds/videos.xml?channel_id=UC…``). Official, keyless, works from a datacenter
when the channel HTML is a consent wall. Titles, dates and feed view counts are
copied; subscriber count is not in the feed and stays unavailable.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as dateparser

from app.config import settings
from app.engine.collectors import browser as br
from app.engine.http import fetch
from app.engine.numbers import parse_human_count
from app.schemas import ContentItem, PlatformAccount

API = "https://www.googleapis.com/youtube/v3"
_YT_INITIAL = re.compile(r"var ytInitialData\s*=\s*(\{.*?\});</script>", re.S)
_CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_\-]{22}")
_CHANNEL_ID_JSON = re.compile(
    r'"(?:externalId|channelId)"\s*:\s*"(UC[A-Za-z0-9_\-]{22})"')
_ATOM = "{http://www.w3.org/2005/Atom}"
_YT_NS = "{http://www.youtube.com/xml/schemas/2015}"
_RSS_NOTE = (
    "Recent uploads came from YouTube's public Atom feed. View counts in that "
    "feed are copied when present; subscriber count is not in the feed."
)


def channel_id_from(handle_or_id: str, html: str = "") -> str:
    """Return a UC… id from a handle, Wikidata channel URL leftover, or page HTML."""
    ident = (handle_or_id or "").strip().lstrip("@")
    if _CHANNEL_ID.fullmatch(ident):
        return ident
    if html:
        found = _CHANNEL_ID_JSON.search(html) or _CHANNEL_ID.search(html)
        if found:
            return found.group(1) if found.lastindex else found.group(0)
    return ""


def parse_atom_feed(xml_text: str) -> dict[str, Any]:
    """Copy entries YouTube published on the channel Atom feed. No invented views."""
    out: dict[str, Any] = {"title": "", "channel_id": "", "videos": []}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    out["title"] = (root.findtext(f"{_ATOM}title") or "").strip()
    out["channel_id"] = (root.findtext(f"{_YT_NS}channelId") or "").strip()
    author = root.find(f"{_ATOM}author")
    if author is not None and not out["title"]:
        out["title"] = (author.findtext(f"{_ATOM}name") or "").strip()
    for entry in root.findall(f"{_ATOM}entry"):
        vid = (entry.findtext(f"{_YT_NS}videoId") or "").strip()
        title = (entry.findtext(f"{_ATOM}title") or "").strip()
        published = (entry.findtext(f"{_ATOM}published") or "").strip()
        views = None
        for el in entry.iter():
            if el.tag.endswith("statistics") and el.attrib.get("views"):
                raw = str(el.attrib.get("views") or "").replace(",", "")
                if raw.isdigit():
                    views = int(raw)
                break
        published_at = None
        if published:
            try:
                published_at = dateparser.parse(published)
            except (ValueError, OverflowError, TypeError):
                published_at = None
        out["videos"].append({
            "id": vid,
            "title": title,
            "url": f"https://www.youtube.com/watch?v={vid}" if vid else None,
            "views": views,
            "published_at": published_at,
        })
    return out


def _parse_compact(text: str | None) -> int | None:
    """Parse compact public counts, including Indian lakh/crore localisation."""
    return parse_human_count(text)


def _duration_to_seconds(txt: str | None) -> int | None:
    if not txt:
        return None
    parts = [p for p in txt.split(":") if p.strip().isdigit()]
    if not parts:
        return None
    secs = 0
    for p in parts:
        secs = secs * 60 + int(p)
    return secs


def _iso_duration(iso: str | None) -> int | None:
    if not iso:
        return None
    m = re.match(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _walk(node: Any, key: str):
    """Depth-first search for every dict carrying `key`."""
    if isinstance(node, dict):
        if key in node:
            yield node[key]
        for v in node.values():
            yield from _walk(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, key)


def _runs(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    if "simpleText" in obj:
        return obj["simpleText"]
    return "".join(r.get("text", "") for r in obj.get("runs", []))


# --------------------------------------------------------------------- API v3
async def _via_api(handle_or_id: str) -> PlatformAccount | None:
    key = settings.youtube_api_key
    if not key:
        return None

    if handle_or_id.startswith("UC"):
        q = (f"{API}/channels?part=snippet,statistics,brandingSettings,contentDetails"
             f"&id={handle_or_id}&key={key}")
    else:
        q = (f"{API}/channels?part=snippet,statistics,brandingSettings,contentDetails"
             f"&forHandle=@{handle_or_id}&key={key}")

    r = await fetch(q, check_robots=False)
    if not r.ok:
        return None
    data = json.loads(r.text)
    items = data.get("items") or []
    if not items:
        return None
    ch = items[0]
    sn, st = ch.get("snippet", {}), ch.get("statistics", {})
    branding = ch.get("brandingSettings", {}).get("channel", {})
    cid = ch["id"]

    acc = PlatformAccount(
        platform="youtube",
        handle=sn.get("customUrl", handle_or_id).lstrip("@"),
        url=f"https://www.youtube.com/channel/{cid}",
        display_name=sn.get("title"),
        bio=sn.get("description"),
        followers=int(st["subscriberCount"]) if st.get("subscriberCount") else None,
        posts=int(st["videoCount"]) if st.get("videoCount") else None,
        keywords=_split_keywords(branding.get("keywords", "")),
        raw={"channel_id": cid, "view_count": st.get("viewCount"), "source": "youtube_api_v3"},
    )

    # Most recent uploads
    uploads = (ch.get("contentDetails", {}) or {}).get("relatedPlaylists", {}).get("uploads")
    ids: list[str] = []
    id_sources: dict[str, set[str]] = {}
    # The uploads playlist is exhaustive and costs one quota unit. ``search.list`` for
    # the latest uploads would cost 100 and can include less stable ordering.
    sr = await fetch(
        f"{API}/playlistItems?part=contentDetails&playlistId={uploads}&maxResults=50&key={key}"
        if uploads else "",
        check_robots=False,
    ) if uploads else None
    if sr and sr.ok:
        recent_ids = [i.get("contentDetails", {}).get("videoId")
                      for i in json.loads(sr.text).get("items", [])]
        recent_ids = [video_id for video_id in recent_ids if video_id]
        ids += recent_ids
        for video_id in recent_ids:
            id_sources.setdefault(video_id, set()).add("latest")
    # Most popular of all time
    pr = await fetch(
        f"{API}/search?part=snippet&channelId={cid}&order=viewCount&type=video&maxResults=50&key={key}",
        check_robots=False,
    )
    if pr.ok:
        popular_ids = [i["id"]["videoId"] for i in json.loads(pr.text).get("items", [])
                       if i.get("id", {}).get("videoId")]
        ids += popular_ids
        for video_id in popular_ids:
            id_sources.setdefault(video_id, set()).add("popular")

    ids = list(dict.fromkeys(ids))
    for chunk_start in range(0, len(ids), 50):
        chunk = ids[chunk_start:chunk_start + 50]
        vr = await fetch(
            f"{API}/videos?part=snippet,statistics,contentDetails&id={','.join(chunk)}&key={key}",
            check_robots=False,
        )
        if not vr.ok:
            continue
        for v in json.loads(vr.text).get("items", []):
            vsn, vst = v.get("snippet", {}), v.get("statistics", {})
            dur = _iso_duration(v.get("contentDetails", {}).get("duration"))
            acc.content.append(ContentItem(
                platform="youtube",
                title=vsn.get("title", ""),
                url=f"https://www.youtube.com/watch?v={v['id']}",
                views=int(vst["viewCount"]) if vst.get("viewCount") else None,
                likes=int(vst["likeCount"]) if vst.get("likeCount") else None,
                comments=int(vst["commentCount"]) if vst.get("commentCount") else None,
                duration_seconds=dur,
                published_at=_safe_dt(vsn.get("publishedAt")),
                kind="short" if (dur or 999) <= 60 else "video",
                raw={"sample": sorted(id_sources.get(v["id"], {"unknown"}))},
            ))
    _dedupe(acc)
    acc.raw["content_scope"] = "latest_50_plus_popular_50"
    acc.raw["content_is_exhaustive"] = False
    return acc


def _safe_dt(s: str | None):
    try:
        return dateparser.parse(s) if s else None
    except Exception:
        return None


def _split_keywords(raw: str) -> list[str]:
    return [k.strip().strip('"') for k in re.split(r'"\s*|,|\s{2,}', raw) if k.strip()][:60]


def _dedupe(acc: PlatformAccount) -> None:
    seen, out = set(), []
    for c in acc.content:
        if c.url in seen:
            continue
        seen.add(c.url)
        out.append(c)
    acc.content = out


# ------------------------------------------------------------------ HTML path
async def _via_html(handle_or_id: str) -> PlatformAccount:
    ident = (handle_or_id or "").strip().lstrip("@")
    base = (f"https://www.youtube.com/channel/{ident}"
            if ident.startswith("UC") else f"https://www.youtube.com/@{ident}")
    acc = PlatformAccount(platform="youtube", handle=ident, url=base,
                          raw={"source": "public_channel_page"})
    cid = channel_id_from(ident)
    if cid:
        acc.raw["channel_id"] = cid

    r = await fetch(f"{base}/videos", check_robots=False)
    if not r.ok:
        acc.errors.append(f"channel page fetch failed (status {r.status})")
        return acc
    found = channel_id_from(ident, r.text)
    if found:
        acc.raw["channel_id"] = found
        acc.url = f"https://www.youtube.com/channel/{found}"

    m = _YT_INITIAL.search(r.text)
    if not m:
        acc.errors.append("ytInitialData not found; page shape changed")
        return acc
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        acc.errors.append("ytInitialData failed to parse")
        return acc

    header = next(_walk(data, "pageHeaderViewModel"), None) or {}
    meta = next(_walk(data, "metadata"), {}) or {}
    ch_meta = meta.get("channelMetadataRenderer", {}) if isinstance(meta, dict) else {}
    acc.display_name = ch_meta.get("title") or _runs(header.get("title", {}))
    acc.bio = ch_meta.get("description")
    acc.keywords = _split_keywords(ch_meta.get("keywords", ""))
    if ch_meta.get("externalId"):
        acc.raw["channel_id"] = ch_meta["externalId"]
        acc.url = f"https://www.youtube.com/channel/{ch_meta['externalId']}"

    # "1.01M subscribers" / "4.5K videos" live in the header metadata rows
    for row in _walk(data, "contentMetadataViewModel"):
        for part in _walk(row, "metadataParts"):
            for p in part if isinstance(part, list) else []:
                txt = (p.get("text") or {}).get("content", "")
                if "subscriber" in txt.lower():
                    acc.followers = _parse_compact(txt)
                elif "video" in txt.lower():
                    acc.posts = _parse_compact(txt)

    for v in _walk(data, "richItemRenderer"):
        vr = (v or {}).get("content", {}).get("videoRenderer")
        if not vr:
            continue
        vid = vr.get("videoId")
        dur = _duration_to_seconds(_runs(vr.get("lengthText", {})))
        acc.content.append(ContentItem(
            platform="youtube",
            title=_runs(vr.get("title", {})),
            url=f"https://www.youtube.com/watch?v={vid}" if vid else None,
            views=_parse_compact(_runs(vr.get("viewCountText", {}))),
            duration_seconds=dur,
            published_relative=_runs(vr.get("publishedTimeText", {})),
            kind="short" if (dur or 999) <= 60 else "video",
        ))
    _dedupe(acc)
    if not acc.content:
        acc.errors.append("no videos parsed from channel page")
    return acc


async def _via_rss(channel_id: str) -> PlatformAccount | None:
    """Official channel Atom feed. No subscriber count. Feed length is not posts."""
    cid = channel_id_from(channel_id)
    if not cid:
        return None
    resp = await fetch(
        f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
        check_robots=False,
    )
    if not resp.ok:
        return None
    parsed = parse_atom_feed(resp.text)
    if not parsed["videos"]:
        return None
    acc = PlatformAccount(
        platform="youtube", handle=cid,
        url=f"https://www.youtube.com/channel/{cid}",
        display_name=parsed.get("title") or None,
        raw={"channel_id": parsed.get("channel_id") or cid,
             "source": "youtube_atom_feed",
             "video_source": "youtube_atom_feed"},
    )
    for row in parsed["videos"]:
        acc.content.append(ContentItem(
            platform="youtube",
            title=row["title"],
            url=row["url"],
            views=row["views"],
            published_at=row["published_at"],
            kind="video",
            raw={"source": "youtube_atom_feed"},
        ))
    _dedupe(acc)
    acc.errors.append(_RSS_NOTE)
    return acc


async def _via_browser(handle_or_id: str) -> PlatformAccount | None:
    """Render the channel page and click the Popular sort — no API key involved.

    This is the tier that reproduces what a human analyst does: open the channel,
    look at Latest, click Popular, read the view counts off the screen.
    """
    if not br.enabled():
        return None
    r = await br.youtube_channel(handle_or_id)
    if not r.ok:
        return None
    d = br.parse_youtube(r.text)
    base = (f"https://www.youtube.com/channel/{handle_or_id}"
            if handle_or_id.startswith("UC") else f"https://www.youtube.com/@{handle_or_id}")
    acc = PlatformAccount(
        platform="youtube", handle=handle_or_id, url=base,
        display_name=d.get("display_name"), followers=d.get("subscribers"),
        posts=d.get("video_count"),
        raw={"source": "browser_render", "sorts": "latest+popular" if d["popular"] else "latest"},
    )
    seen = set()
    for kind, rows in (("latest", d["videos"]), ("popular", d["popular"])):
        for v in rows:
            key = v["title"][:70]
            if key in seen:
                continue
            seen.add(key)
            acc.content.append(ContentItem(
                platform="youtube", title=v["title"], views=v["views"],
                duration_seconds=v.get("duration_seconds"),
                published_relative=v.get("published_relative"),
                kind="short" if (v.get("duration_seconds") or 999) <= 60 else "video",
                raw={"sort": kind},
            ))
    if r.notes:
        acc.raw["notes"] = r.notes
    return acc if acc.content else None


def _attach_rss(host: PlatformAccount, rss_acc: PlatformAccount) -> PlatformAccount:
    host.content = rss_acc.content
    host.raw["video_source"] = "youtube_atom_feed"
    if rss_acc.display_name and not host.display_name:
        host.display_name = rss_acc.display_name
    cid = rss_acc.raw.get("channel_id")
    if cid:
        host.raw["channel_id"] = cid
        host.url = rss_acc.url
    if _RSS_NOTE not in host.errors:
        host.errors.append(_RSS_NOTE)
    return host


async def collect(handle_or_id: str) -> PlatformAccount:
    """Four tiers, cheapest and most reliable first.

    1. Official Data API   — exact numbers, needs a free key
    2. Browser render      — no key, gets Latest *and* Popular sorts
    3. Plain HTTP parse    — no key, Latest only, breaks when YouTube changes markup
    4. Public Atom feed    — no key, recent uploads, works behind a consent wall
    """
    api_acc = await _via_api(handle_or_id)
    if api_acc and api_acc.content:
        return api_acc

    if settings.browser_mode in ("auto", "always") and br.enabled():
        b_acc = await _via_browser(handle_or_id)
        if b_acc:
            if api_acc:                     # API had stats but no videos
                api_acc.content = b_acc.content
                api_acc.raw["video_source"] = "browser_render"
                return api_acc
            return b_acc

    html_acc = await _via_html(handle_or_id)
    if api_acc and html_acc.content:
        api_acc.content = html_acc.content
        return api_acc
    if html_acc.content:
        return html_acc

    cid = (html_acc.raw.get("channel_id")
           or (api_acc.raw.get("channel_id") if api_acc else "")
           or channel_id_from(handle_or_id))
    rss_acc = await _via_rss(cid) if cid else None
    if rss_acc and rss_acc.content:
        return _attach_rss(api_acc or html_acc, rss_acc)

    if not html_acc.content:
        if not br.available():
            html_acc.errors.append(br.INSTALL_HINT)
        else:
            html_acc.errors.append(
                "The channel page rendered but no videos could be parsed. Either the "
                "channel is empty — which usually means this is not the creator's real "
                "channel — or YouTube changed its markup.")
    return api_acc or html_acc
