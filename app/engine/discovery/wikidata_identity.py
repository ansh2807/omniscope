"""Wikidata identity for a social handle — official, keyless, no login.

When Instagram (or YouTube / X) serves a login wall, the handle is still a public
identifier. Wikidata records that identifier as a structured claim:

  * P2003 Instagram username
  * P2397 YouTube channel ID
  * P2002 X / Twitter username
  * P7085 TikTok username
  * P6634 LinkedIn personal profile ID
  * P2013 Facebook username
  * P1902 Spotify artist ID
  * P4265 Reddit username
  * P5842 Apple Podcasts podcast ID
  * P5916 Spotify show ID
  * P12361 Bluesky handle
  * P4033 Mastodon address (acct, never guessed from Instagram)
  * P2037 GitHub username (never guessed from Instagram)
  * P3040 SoundCloud username (never guessed from Instagram)
  * P3836 Pinterest username (never guessed from Instagram)
  * P7171 Hacker News username (never guessed from Instagram)
  * P496  ORCID iD (identifier, not a social audience)
  * P434  MusicBrainz artist ID (not monthly listeners)
  * P1448 official name (not a guessed display name)
  * P793  significant event (item labels, not a product launch we invented)
  * P106  occupation (item labels, never audience jobs)
  * P166  award received (item labels, not a ceremony date unless printed)
  * P800  notable work (item labels, not a product catalog)
  * P69   educated at (schools, not audience education)
  * P108  employer
  * P937  work location (not a city inferred from citizenship)
  * P39   position held (official office, not an occupation or audience job)
  * P551  residence (labelled residence, never citizenship or work location)
  * P19   place of birth (labelled birthplace, never current location)
  * P742  pseudonym (printed alias, never a guessed display name)
  * P101  field of work (not a content calendar)
  * P136  genre
  * P1412 languages spoken or written
  * P1411 nominated for (not an award win; that is P166)
  * P1344 participant in (events, not employers)
  * P463  member of (organisations, not audience membership)
  * P27   country of citizenship (item labels, not a city)
  * P856  official website
  * P18   Commons image (not an Instagram avatar or profile photo)
  * P8687 social-media followers, only when a platform qualifier is present

Nothing here is scraped from a login-walled grid. Counts are copied from Wikidata
and labelled as Wikidata, never as an Instagram page reading.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, quote_plus, urlparse

from app.engine.collectors.github import profile_url as github_profile_url
from app.engine.collectors.github import username_from as github_username
from app.engine.collectors.mastodon import profile_from_claim as mastodon_profile_url
from app.engine.collectors.hackernews import profile_url as hackernews_profile_url
from app.engine.collectors.hackernews import username_from as hackernews_username
from app.engine.collectors.pinterest import profile_url as pinterest_profile_url
from app.engine.collectors.pinterest import username_from as pinterest_username
from app.engine.collectors.soundcloud import profile_url as soundcloud_profile_url
from app.engine.collectors.soundcloud import username_from as soundcloud_username
from app.engine.discovery.public_records import musicbrainz_id
from app.engine.http import fetch

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")

SOCIAL_PROPS = {
    "instagram": "P2003",
    "youtube": "P2397",
    "x": "P2002",
}
OFFICIAL_IDS = {
    "sec_cik": ("P5531", None),
    "lei": ("P1278", None),
    "viaf": ("P214", "https://viaf.org/viaf/{id}/"),
    "lccn": ("P244", "https://id.loc.gov/authorities/names/{id}"),
    "gnd": ("P227", "https://d-nb.info/gnd/{id}"),
    "imdb": ("P345", "https://www.imdb.com/name/{id}/"),
    "isin": ("P946", None),
    "companies_house": (
        "P2622",
        "https://find-and-update.company-information.service.gov.uk/company/{id}",
    ),
    "opencorporates": ("P1320", "https://opencorporates.com/companies/{id}"),
}

EXTRA_SOCIAL = {
    "tiktok": ("P7085", "https://www.tiktok.com/@{handle}"),
    "linkedin": ("P6634", "https://www.linkedin.com/in/{handle}/"),
    "facebook": ("P2013", "https://www.facebook.com/{handle}"),
    "spotify": ("P1902", "https://open.spotify.com/artist/{handle}"),
    "reddit": ("P4265", "https://www.reddit.com/user/{handle}"),
    "apple_podcast": ("P5842", "https://podcasts.apple.com/podcast/id{handle}"),
    "spotify_show": ("P5916", "https://open.spotify.com/show/{handle}"),
    "bluesky": ("P12361", "https://bsky.app/profile/{handle}"),
}
PLATFORM_QIDS = {
    "Q209330": "instagram",
    "Q866": "youtube",
    "Q918": "x",
    "Q20663908": "x",
    "Q112043378": "x",
    "Q11649": "tiktok",
    "Q355": "facebook",
    "Q1136": "reddit",
    "Q109813218": "bluesky",
    "Q198028": "mastodon",
    "Q364": "github",
    "Q568769": "soundcloud",
    "Q384562": "pinterest",
    "Q686797": "hackernews",
}


WIKIMEDIA_HOSTS = frozenset({"upload.wikimedia.org", "commons.wikimedia.org"})


def is_wikimedia_image(url: str) -> bool:
    """True only for official Wikimedia image hosts. Instagram CDNs stay out."""
    try:
        parts = urlparse(url)
    except Exception:
        return False
    host = (parts.netloc or "").lower()
    if host not in WIKIMEDIA_HOSTS:
        return False
    return parts.scheme in ("http", "https") and bool(parts.path.strip("/"))


def commons_file_url(value: str) -> str:
    """P18 filename or Commons URL → Special:FilePath. Other hosts stay empty."""
    text = (value or "").strip()
    if not text:
        return ""
    if text.lower().startswith("http"):
        return text if is_wikimedia_image(text) else ""
    name = text.replace(" ", "_")
    if "/" in name or "\\" in name or ".." in name:
        return ""
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(name, safe='_.-')}"


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def handle_matches(claim: str, handle: str) -> bool:
    a, b = _compact(claim), _compact(handle)
    return bool(a and b and a == b)


def titles_match_subject(subject: str, title: str) -> bool:
    """True when a Wikipedia/Wikidata label is the same person as a handle or name.

    ``democreator`` and ``Demo Creator`` are the same compact string. A hit whose
    title shares no token and no compact form is rejected.
    """
    subj = (subject or "").strip()
    tit = (title or "").strip()
    if not subj or not tit:
        return False
    subj_tokens = {t for t in re.split(r"\W+", subj.lower()) if len(t) > 2}
    title_tokens = {t for t in re.split(r"\W+", tit.lower()) if len(t) > 2}
    if subj_tokens and title_tokens and subj_tokens & title_tokens:
        return True
    sc, tc = _compact(subj), _compact(tit)
    if len(sc) >= 5 and len(tc) >= 5 and (sc == tc or sc in tc or tc in sc):
        return True
    return False


def _string_claim(entity: dict, prop: str) -> str:
    for claim in (entity.get("claims") or {}).get(prop) or []:
        if not isinstance(claim, dict):
            continue
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _string_claims(entity: dict, prop: str) -> list[str]:
    out: list[str] = []
    for claim in (entity.get("claims") or {}).get(prop) or []:
        if not isinstance(claim, dict):
            continue
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(value, str) and value.strip() and value not in out:
            out.append(value.strip())
    return out


def _text_claims(entity: dict, prop: str) -> list[str]:
    """String or monolingualtext claims. Item Q-ids and URLs stay out."""
    out: list[str] = []
    for claim in (entity.get("claims") or {}).get(prop) or []:
        if not isinstance(claim, dict):
            continue
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        text = ""
        if isinstance(value, str):
            text = value.strip()
        elif isinstance(value, dict):
            text = str(value.get("text") or "").strip()
        if not text or text in out:
            continue
        if text.lower().startswith(("http://", "https://")):
            continue
        if re.fullmatch(r"Q\d+", text):
            continue
        if len(text) > 80:
            continue
        out.append(text)
    return out


def parse_official_ids(entity: dict) -> dict[str, str]:
    """Copy official identifiers already on the Wikidata item. Never guess."""
    out: dict[str, str] = {}
    if not isinstance(entity, dict):
        return out
    for name, (prop, template) in OFFICIAL_IDS.items():
        value = _string_claim(entity, prop).strip()
        if not value:
            continue
        if name == "sec_cik":
            digits = re.sub(r"\D", "", value)
            if not digits:
                continue
            value = digits.zfill(10)
            out[name] = value
            out[f"{name}_url"] = (
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={value}")
            continue
        if name == "lei":
            compact = re.sub(r"\s+", "", value.upper())
            if not re.fullmatch(r"[A-Z0-9]{20}", compact):
                continue
            value = compact
        if name == "imdb" and value.startswith("tt"):
            template = "https://www.imdb.com/title/{id}/"
        out[name] = value[:80]
        if template:
            out[f"{name}_url"] = template.format(id=value)
    return out


def orcid_from(value: str) -> str:
    """ORCID iD from a bare id or orcid.org URL. Other strings stay empty."""
    text = (value or "").strip()
    if "orcid.org/" in text.lower():
        text = text.rstrip("/").split("/")[-1]
    return text if ORCID_RE.fullmatch(text) else ""


def _usable_aliases(values: list[str], *reject: str) -> list[str]:
    """Drop aliases that are just the handle or the item label."""
    skip = {_compact(item) for item in reject if item}
    out: list[str] = []
    for raw in values:
        text = (raw or "").strip().lstrip("@")
        key = _compact(text)
        if not key or key in skip or text in out:
            continue
        out.append(text)
        skip.add(key)
    return out


def _qualifier_qids(claim: dict) -> set[str]:
    ids: set[str] = set()
    for snaks in (claim.get("qualifiers") or {}).values():
        if not isinstance(snaks, list):
            continue
        for snak in snaks:
            if not isinstance(snak, dict):
                continue
            value = ((snak.get("datavalue") or {}).get("value"))
            if isinstance(value, dict) and isinstance(value.get("id"), str):
                ids.add(value["id"])
    return ids


def _point_in_time(claim: dict) -> str:
    for snak in (claim.get("qualifiers") or {}).get("P585") or []:
        if not isinstance(snak, dict):
            continue
        value = ((snak.get("datavalue") or {}).get("value"))
        if not isinstance(value, dict):
            continue
        stamp = str(value.get("time") or "")
        match = re.search(r"(\d{4}-\d{2}-\d{2})", stamp)
        if match:
            return match.group(1)
    return ""


def _quantity(claim: dict) -> int | None:
    value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
    if not isinstance(value, dict):
        return None
    raw = str(value.get("amount") or "").replace("+", "").replace(",", "")
    try:
        amount = int(float(raw))
    except ValueError:
        return None
    return amount if amount > 0 else None


def item_qids(entity: dict, prop: str) -> list[str]:
    """Q-ids from an item-valued claim. Body text that happens to look like Q1 is ignored."""
    out: list[str] = []
    for claim in (entity.get("claims") or {}).get(prop) or []:
        if not isinstance(claim, dict):
            continue
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if not isinstance(value, dict):
            continue
        qid = value.get("id")
        if isinstance(qid, str) and re.fullmatch(r"Q\d+", qid) and qid not in out:
            out.append(qid)
    return out


async def labels_for(qids: list[str]) -> dict[str, str]:
    """English labels for Wikidata items. Missing labels stay absent."""
    ids = [q for q in qids if re.fullmatch(r"Q\d+", q)][:32]
    if not ids:
        return {}
    url = ("https://www.wikidata.org/w/api.php?action=wbgetentities"
           f"&ids={quote_plus('|'.join(ids))}&props=labels&languages=en&format=json")
    resp = await fetch(url, check_robots=False)
    if not resp.ok:
        return {}
    try:
        body = json.loads(resp.text)
    except json.JSONDecodeError:
        return {}
    out: dict[str, str] = {}
    entities = body.get("entities") if isinstance(body, dict) else None
    if not isinstance(entities, dict):
        return {}
    for qid, row in entities.items():
        if not isinstance(row, dict):
            continue
        en = ((row.get("labels") or {}).get("en") or {})
        name = str(en.get("value") or "").strip() if isinstance(en, dict) else ""
        if name:
            out[str(qid)] = name
    return out


def parse_followers(entity: dict) -> list[dict[str, Any]]:
    """P8687 rows that name a platform. No platform qualifier → skipped."""
    rows: list[dict[str, Any]] = []
    for claim in (entity.get("claims") or {}).get("P8687") or []:
        if not isinstance(claim, dict):
            continue
        count = _quantity(claim)
        if not count:
            continue
        platforms = {PLATFORM_QIDS[qid] for qid in _qualifier_qids(claim)
                     if qid in PLATFORM_QIDS}
        if not platforms:
            continue
        as_of = _point_in_time(claim)
        for platform in sorted(platforms):
            rows.append({"platform": platform, "count": count, "as_of": as_of})
    return rows


def parse_entity(entity: dict, *, platform: str, handle: str) -> dict[str, Any] | None:
    """Return identity fields only if the social-handle claim matches *handle*."""
    prop = SOCIAL_PROPS.get(platform)
    if not prop:
        return None
    claimed = _string_claim(entity, prop)
    if not claimed:
        return None
    ident = (handle or "").strip().lstrip("@")
    if platform == "youtube" and ident.startswith("UC"):
        if not handle_matches(claimed, ident):
            return None
    elif platform != "youtube" and not handle_matches(claimed, ident):
        return None

    ident_qid = str(entity.get("id") or "")
    labels = entity.get("labels") or {}
    label = ""
    if isinstance(labels, dict):
        en = labels.get("en") or {}
        if isinstance(en, dict):
            label = str(en.get("value") or "").strip()
    sitelinks = entity.get("sitelinks") or {}
    wiki_title = ""
    if isinstance(sitelinks, dict):
        enwiki = sitelinks.get("enwiki") or {}
        if isinstance(enwiki, dict):
            wiki_title = str(enwiki.get("title") or "").strip()

    youtube = _string_claim(entity, "P2397")
    twitter = _string_claim(entity, "P2002")
    sites = [u for u in _string_claims(entity, "P856") if u.startswith("http")]
    readings = parse_followers(entity)
    seed_reading = next((row for row in readings if row["platform"] == platform), None)

    youtube_url = ""
    if youtube.startswith("UC"):
        youtube_url = f"https://www.youtube.com/channel/{youtube}"
    twitter_url = f"https://x.com/{twitter}" if twitter else ""

    descriptions = entity.get("descriptions") or {}
    description = ""
    if isinstance(descriptions, dict):
        en_desc = descriptions.get("en") or {}
        if isinstance(en_desc, dict):
            description = str(en_desc.get("value") or "").strip()

    extras: dict[str, str] = {}
    for name, (prop, template) in EXTRA_SOCIAL.items():
        value = _string_claim(entity, prop).lstrip("@").strip().strip("/")
        if value:
            extras[f"{name}_url"] = template.format(handle=value)
    github_login = github_username(_string_claim(entity, "P2037"))
    soundcloud_login = soundcloud_username(_string_claim(entity, "P3040"))
    pinterest_login = pinterest_username(_string_claim(entity, "P3836"))
    hackernews_login = hackernews_username(_string_claim(entity, "P7171"))
    orcid = orcid_from(_string_claim(entity, "P496"))
    mbid = musicbrainz_id(_string_claim(entity, "P434"))
    official = parse_official_ids(entity)

    return {
        "id": ident_qid,
        "label": label or None,
        "description": description or None,
        "wikipedia_title": wiki_title or None,
        "youtube_channel_url": youtube_url or None,
        "twitter_url": twitter_url or None,
        "tiktok_url": extras.get("tiktok_url"),
        "linkedin_url": extras.get("linkedin_url"),
        "facebook_url": extras.get("facebook_url"),
        "spotify_url": extras.get("spotify_url"),
        "reddit_url": extras.get("reddit_url"),
        "podcast_url": extras.get("apple_podcast_url") or extras.get("spotify_show_url"),
        "bluesky_url": extras.get("bluesky_url"),
        "mastodon_url": mastodon_profile_url(_string_claim(entity, "P4033")) or None,
        "github_url": github_profile_url(github_login) if github_login else None,
        "soundcloud_url": (soundcloud_profile_url(soundcloud_login)
                           if soundcloud_login else None),
        "pinterest_url": (pinterest_profile_url(pinterest_login)
                          if pinterest_login else None),
        "hackernews_url": (hackernews_profile_url(hackernews_login)
                           if hackernews_login else None),
        "orcid": orcid or None,
        "musicbrainz_id": mbid or None,
        "official_ids": {k: v for k, v in official.items() if not k.endswith("_url")},
        "official_id_urls": {k[:-4]: v for k, v in official.items() if k.endswith("_url")},
        "official_names": _usable_aliases(
            _text_claims(entity, "P1448"), handle, ident, label, wiki_title,
            *_text_claims(entity, "P742")),
        "image_url": commons_file_url(_string_claim(entity, "P18")) or None,
        "occupation_qids": item_qids(entity, "P106"),
        "citizenship_qids": item_qids(entity, "P27"),
        "award_qids": item_qids(entity, "P166"),
        "notable_work_qids": item_qids(entity, "P800"),
        "education_qids": item_qids(entity, "P69"),
        "employer_qids": item_qids(entity, "P108"),
        "work_location_qids": item_qids(entity, "P937"),
        "position_qids": item_qids(entity, "P39"),
        "residence_qids": item_qids(entity, "P551"),
        "birth_place_qids": item_qids(entity, "P19"),
        "pseudonyms": _usable_aliases(
            _text_claims(entity, "P742"), handle, ident, label, wiki_title),
        "significant_event_qids": item_qids(entity, "P793"),
        "field_of_work_qids": item_qids(entity, "P101"),
        "genre_qids": item_qids(entity, "P136"),
        "language_qids": item_qids(entity, "P1412"),
        "nominated_for_qids": item_qids(entity, "P1411"),
        "participant_qids": item_qids(entity, "P1344"),
        "member_qids": item_qids(entity, "P463"),
        "sites": sites,
        "follower_readings": readings,
        "followers": seed_reading["count"] if seed_reading else None,
        "followers_as_of": (seed_reading or {}).get("as_of") or None,
        "followers_platform": seed_reading["platform"] if seed_reading else None,
    }


def _qid_from_search(payload: dict) -> str:
    rows = (payload or {}).get("query", {}).get("search") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return ""
    for row in rows:
        title = str((row or {}).get("title") or "")
        if re.fullmatch(r"Q\d+", title):
            return title
    return ""


async def _entities(qid: str) -> dict:
    url = ("https://www.wikidata.org/w/api.php?action=wbgetentities"
           f"&ids={quote_plus(qid)}&props=labels|descriptions|claims|sitelinks"
           "&languages=en&format=json")
    resp = await fetch(url, check_robots=False)
    if not resp.ok:
        return {}
    try:
        body = json.loads(resp.text)
    except json.JSONDecodeError:
        return {}
    row = ((body.get("entities") or {}).get(qid) or {})
    return row if isinstance(row, dict) else {}


async def lookup(platform: str, handle: str) -> dict[str, Any] | None:
    """Resolve a social handle to a Wikidata item that actually claims that handle."""
    prop = SOCIAL_PROPS.get(platform)
    ident = (handle or "").strip().lstrip("@")
    if not prop or len(ident) < 2:
        return None
    search = ("https://www.wikidata.org/w/api.php?action=query&list=search"
              f"&srsearch={quote_plus(f'haswbstatement:{prop}={ident}')}"
              "&srnamespace=0&format=json")
    resp = await fetch(search, check_robots=False)
    qid = ""
    if resp.ok:
        try:
            qid = _qid_from_search(json.loads(resp.text))
        except json.JSONDecodeError:
            qid = ""
    if not qid and ident != ident.lower():
        return await lookup(platform, ident.lower())
    if not qid:
        return None
    entity = await _entities(qid)
    parsed = parse_entity(entity, platform=platform, handle=ident)
    if parsed is None and ident != ident.lower():
        parsed = parse_entity(entity, platform=platform, handle=ident.lower())
    if parsed is None:
        return None
    qids: list[str] = []
    for key in ("occupation_qids", "citizenship_qids", "award_qids",
                "notable_work_qids", "education_qids", "employer_qids",
                "work_location_qids", "position_qids", "residence_qids",
                "birth_place_qids", "significant_event_qids",
                "field_of_work_qids", "genre_qids",
                "language_qids", "nominated_for_qids", "participant_qids",
                "member_qids"):
        qids.extend(parsed.get(key) or [])
    names = await labels_for(qids)
    parsed["occupations"] = [names[q] for q in (parsed.get("occupation_qids") or [])
                             if names.get(q)]
    parsed["citizenships"] = [names[q] for q in (parsed.get("citizenship_qids") or [])
                              if names.get(q)]
    parsed["awards"] = [names[q] for q in (parsed.get("award_qids") or [])
                        if names.get(q)]
    parsed["notable_works"] = [names[q] for q in (parsed.get("notable_work_qids") or [])
                               if names.get(q)]
    parsed["education"] = [names[q] for q in (parsed.get("education_qids") or [])
                           if names.get(q)]
    parsed["employers"] = [names[q] for q in (parsed.get("employer_qids") or [])
                           if names.get(q)]
    parsed["work_locations"] = [names[q] for q in (parsed.get("work_location_qids") or [])
                               if names.get(q)]
    parsed["positions"] = [names[q] for q in (parsed.get("position_qids") or [])
                           if names.get(q)]
    parsed["residences"] = [names[q] for q in (parsed.get("residence_qids") or [])
                            if names.get(q)]
    parsed["birth_places"] = [names[q] for q in (parsed.get("birth_place_qids") or [])
                              if names.get(q)]
    parsed["significant_events"] = [
        names[q] for q in (parsed.get("significant_event_qids") or [])
        if names.get(q)]
    parsed["fields_of_work"] = [names[q] for q in (parsed.get("field_of_work_qids") or [])
                                if names.get(q)]
    parsed["genres"] = [names[q] for q in (parsed.get("genre_qids") or [])
                        if names.get(q)]
    parsed["languages"] = [names[q] for q in (parsed.get("language_qids") or [])
                           if names.get(q)]
    parsed["nominations"] = [names[q] for q in (parsed.get("nominated_for_qids") or [])
                             if names.get(q)]
    parsed["participations"] = [names[q] for q in (parsed.get("participant_qids") or [])
                                if names.get(q)]
    parsed["memberships"] = [names[q] for q in (parsed.get("member_qids") or [])
                             if names.get(q)]
    return parsed
