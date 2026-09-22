"""Wikidata / Wikipedia identity matching — no invented follower counts."""
from __future__ import annotations

import asyncio
import json

from app.engine.assemble import build
from app.engine.discovery import keyless, verify, wikidata_identity
from app.engine.inference.content import recurring_title_tokens
from app.engine.pipeline import _apply_keyless_identity, _apply_wikidata_followers
from app.schemas import ContentItem, PlatformAccount, RawProfile


DEMO = {
    "id": "Q123",
    "labels": {"en": {"value": "Demo Creator"}},
    "descriptions": {"en": {"value": "Indian podcaster and entrepreneur"}},
    "sitelinks": {"enwiki": {"title": "Demo Creator"}},
    "claims": {
        "P2003": [{"mainsnak": {"datavalue": {"value": "democreator"}}}],
        "P2397": [{"mainsnak": {"datavalue": {"value": "UC1234567890123456789012"}}}],
        "P2002": [{"mainsnak": {"datavalue": {"value": "democreator"}}}],
        "P7085": [{"mainsnak": {"datavalue": {"value": "democreator"}}}],
        "P6634": [{"mainsnak": {"datavalue": {"value": "democreator"}}}],
        "P2013": [{"mainsnak": {"datavalue": {"value": "democreator"}}}],
        "P1902": [{"mainsnak": {"datavalue": {"value": "1abcSpotifyId22"}}}],
        "P4265": [{"mainsnak": {"datavalue": {"value": "democreator"}}}],
        "P5842": [{"mainsnak": {"datavalue": {"value": "1530805412"}}}],
        "P5916": [{"mainsnak": {"datavalue": {"value": "abcdefghij0123456789ab"}}}],
        "P12361": [{"mainsnak": {"datavalue": {"value": "democreator.bsky.social"}}}],
        "P4033": [{"mainsnak": {"datavalue": {"value": "democreator@mastodon.social"}}}],
        "P2037": [{"mainsnak": {"datavalue": {"value": "democreator"}}}],
        "P3040": [{"mainsnak": {"datavalue": {"value": "democreator"}}}],
        "P3836": [{"mainsnak": {"datavalue": {"value": "democreator"}}}],
        "P7171": [{"mainsnak": {"datavalue": {"value": "democreator"}}}],
        "P496": [{"mainsnak": {"datavalue": {"value": "0000-0002-1825-0097"}}}],
        "P5531": [{"mainsnak": {"datavalue": {"value": "320193"}}}],
        "P1278": [{"mainsnak": {"datavalue": {"value": "5493001KJTIIGC8Y1R12"}}}],
        "P214": [{"mainsnak": {"datavalue": {"value": "12345678"}}}],
        "P434": [{"mainsnak": {"datavalue": {"value": "a74b1b7f-71a5-4011-9441-d0b5e4122711"}}}],
        "P1448": [{"mainsnak": {"datavalue": {"value": {"text": "Figuring Out Media", "language": "en"}}}}],
        "P793": [{"mainsnak": {"datavalue": {"value": {"id": "Q666"}}}}],
        "P18": [{"mainsnak": {"datavalue": {"value": "Demo Creator.jpg"}}}],
        "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q33999"}}}}],
        "P166": [{"mainsnak": {"datavalue": {"value": {"id": "Q12345"}}}}],
        "P800": [{"mainsnak": {"datavalue": {"value": {"id": "Q24634"}}}}],
        "P69": [{"mainsnak": {"datavalue": {"value": {"id": "Q789"}}}}],
        "P108": [{"mainsnak": {"datavalue": {"value": {"id": "Q111"}}}}],
        "P937": [{"mainsnak": {"datavalue": {"value": {"id": "Q1156"}}}}],
        "P39": [{"mainsnak": {"datavalue": {"value": {"id": "Q484876"}}}}],
        "P551": [{"mainsnak": {"datavalue": {"value": {"id": "Q987"}}}}],
        "P19": [{"mainsnak": {"datavalue": {"value": {"id": "Q555"}}}}],
        "P742": [
            {"mainsnak": {"datavalue": {"value": {"text": "Demo Show", "language": "en"}}}},
            {"mainsnak": {"datavalue": {"value": "democreator"}}},
            {"mainsnak": {"datavalue": {"value": "https://example.com/alias"}}},
        ],
        "P101": [{"mainsnak": {"datavalue": {"value": {"id": "Q10186"}}}}],
        "P136": [{"mainsnak": {"datavalue": {"value": {"id": "Q211467"}}}}],
        "P1412": [{"mainsnak": {"datavalue": {"value": {"id": "Q1860"}}}}],
        "P1411": [{"mainsnak": {"datavalue": {"value": {"id": "Q222"}}}}],
        "P1344": [{"mainsnak": {"datavalue": {"value": {"id": "Q333"}}}}],
        "P463": [{"mainsnak": {"datavalue": {"value": {"id": "Q444"}}}}],
        "P27": [{"mainsnak": {"datavalue": {"value": {"id": "Q668"}}}}],
        "P856": [{"mainsnak": {"datavalue": {"value": "https://www.figuringout.co/"}}}],
        "P8687": [{
            "mainsnak": {"datavalue": {"value": {"amount": "+9600000", "unit": "1"}}},
            "qualifiers": {
                "P585": [{"datavalue": {"value": {"time": "+2024-06-01T00:00:00Z"}}}],
                "P518": [{"datavalue": {"value": {"id": "Q209330"}}}],
            },
        }, {
            "mainsnak": {"datavalue": {"value": {"amount": "+5000000", "unit": "1"}}},
            "qualifiers": {
                "P585": [{"datavalue": {"value": {"time": "+2024-01-01T00:00:00Z"}}}],
                "P518": [{"datavalue": {"value": {"id": "Q866"}}}],
            },
        }],
    },
}


def test_titles_match_concatenated_handle():
    assert wikidata_identity.titles_match_subject("democreator", "Demo Creator")
    assert wikidata_identity.titles_match_subject("Demo Creator", "Demo Creator")
    assert not wikidata_identity.titles_match_subject(
        "Sunil Panda", "Completely Different Person")


def test_wikipedia_accepts_concatenated_handle():
    class FakeResp:
        def __init__(self, payload):
            self.ok = True
            self.text = json.dumps(payload)

    async def fake_fetch(url, **_kw):
        if "list=search" in url:
            return FakeResp({"query": {"search": [{"title": "Demo Creator"}]}})
        if "page/summary" in url:
            return FakeResp({
                "title": "Demo Creator",
                "extract": "Indian podcaster.",
                "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Demo_Creator"}},
                "originalimage": {
                    "source": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Demo_Creator.jpg",
                },
            })
        return FakeResp({"query": {"pages": {}}})

    orig = keyless.fetch
    keyless.fetch = fake_fetch
    try:
        out = asyncio.run(keyless.wikipedia("democreator"))
    finally:
        keyless.fetch = orig
    assert out["title"] == "Demo Creator"
    assert "podcaster" in out["extract"]
    assert out["image_url"] == (
        "https://upload.wikimedia.org/wikipedia/commons/a/ab/Demo_Creator.jpg")
    assert out["image_source"] == "wikipedia_summary"


def test_parse_entity_requires_matching_handle_and_platform_qualifier():
    parsed = wikidata_identity.parse_entity(
        DEMO, platform="instagram", handle="democreator")
    assert parsed is not None
    assert parsed["label"] == "Demo Creator"
    assert parsed["description"] == "Indian podcaster and entrepreneur"
    assert parsed["sites"] == ["https://www.figuringout.co/"]
    assert parsed["youtube_channel_url"].endswith("UC1234567890123456789012")
    assert parsed["tiktok_url"] == "https://www.tiktok.com/@democreator"
    assert parsed["linkedin_url"] == "https://www.linkedin.com/in/democreator/"
    assert parsed["facebook_url"] == "https://www.facebook.com/democreator"
    assert parsed["spotify_url"] == "https://open.spotify.com/artist/1abcSpotifyId22"
    assert parsed["reddit_url"] == "https://www.reddit.com/user/democreator"
    assert parsed["podcast_url"] == "https://podcasts.apple.com/podcast/id1530805412"
    assert parsed["bluesky_url"] == "https://bsky.app/profile/democreator.bsky.social"
    assert parsed["mastodon_url"] == "https://mastodon.social/@democreator"
    assert parsed["github_url"] == "https://github.com/democreator"
    assert parsed["soundcloud_url"] == "https://soundcloud.com/democreator"
    assert parsed["pinterest_url"] == "https://www.pinterest.com/democreator/"
    assert parsed["hackernews_url"] == "https://news.ycombinator.com/user?id=democreator"
    assert parsed["orcid"] == "0000-0002-1825-0097"
    assert parsed["official_ids"]["sec_cik"] == "0000320193"
    assert parsed["official_ids"]["lei"] == "5493001KJTIIGC8Y1R12"
    assert parsed["official_id_urls"]["viaf"].endswith("/12345678/")
    assert parsed["musicbrainz_id"] == "a74b1b7f-71a5-4011-9441-d0b5e4122711"
    assert parsed["official_names"] == ["Figuring Out Media"]
    assert parsed["significant_event_qids"] == ["Q666"]
    assert parsed["image_url"] == (
        "https://commons.wikimedia.org/wiki/Special:FilePath/Demo_Creator.jpg")
    assert parsed["award_qids"] == ["Q12345"]
    assert parsed["notable_work_qids"] == ["Q24634"]
    assert parsed["education_qids"] == ["Q789"]
    assert parsed["employer_qids"] == ["Q111"]
    assert parsed["work_location_qids"] == ["Q1156"]
    assert parsed["position_qids"] == ["Q484876"]
    assert parsed["residence_qids"] == ["Q987"]
    assert parsed["birth_place_qids"] == ["Q555"]
    assert parsed["pseudonyms"] == ["Demo Show"]
    assert parsed["field_of_work_qids"] == ["Q10186"]
    assert parsed["genre_qids"] == ["Q211467"]
    assert parsed["language_qids"] == ["Q1860"]
    assert parsed["nominated_for_qids"] == ["Q222"]
    assert parsed["participant_qids"] == ["Q333"]
    assert parsed["member_qids"] == ["Q444"]
    assert parsed["occupation_qids"] == ["Q33999"]
    assert parsed["citizenship_qids"] == ["Q668"]
    assert {row["platform"]: row["count"] for row in parsed["follower_readings"]} == {
        "instagram": 9_600_000, "youtube": 5_000_000,
    }
    assert parsed["followers"] == 9_600_000
    assert parsed["followers_as_of"] == "2024-06-01"
    assert parsed["followers_platform"] == "instagram"
    assert wikidata_identity.parse_entity(
        DEMO, platform="instagram", handle="someoneelse") is None


def test_bluesky_and_orcid_are_never_guessed_from_instagram():
    entity = {
        "id": "Q1",
        "labels": {"en": {"value": "Ada"}},
        "claims": {
            "P2003": [{"mainsnak": {"datavalue": {"value": "ada"}}}],
        },
    }
    parsed = wikidata_identity.parse_entity(entity, platform="instagram", handle="ada")
    assert parsed is not None
    assert parsed["bluesky_url"] is None
    assert parsed["orcid"] is None
    assert parsed["official_ids"] == {}


def test_wikimedia_portrait_rejects_other_hosts():
    assert wikidata_identity.commons_file_url("Demo Creator.jpg").endswith(
        "Demo_Creator.jpg")
    assert wikidata_identity.commons_file_url(
        "https://upload.wikimedia.org/wikipedia/commons/a/ab/Demo.jpg")
    assert wikidata_identity.commons_file_url(
        "https://scontent.cdninstagram.com/v/t51.2885-19/x.jpg") == ""
    assert not wikidata_identity.is_wikimedia_image(
        "https://scontent.cdninstagram.com/v/t51.2885-19/x.jpg")
    assert keyless.parse_summary_image({
        "thumbnail": {"source": "https://scontent.cdninstagram.com/v/t51.2885-19/x.jpg"},
    }) == {}
    assert keyless.parse_summary_image({
        "originalimage": {
            "source": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Demo.jpg",
        },
        "thumbnail": {"source": "https://scontent.cdninstagram.com/v/t51.2885-19/x.jpg"},
    })["image_source"] == "wikipedia_summary"


def test_github_claim_rejects_repos_and_reserved_paths():
    entity = {
        "id": "Q1",
        "labels": {"en": {"value": "X"}},
        "claims": {
            "P2003": [{"mainsnak": {"datavalue": {"value": "x"}}}],
            "P2037": [{"mainsnak": {"datavalue": {"value": "octocat/repo"}}}],
        },
    }
    parsed = wikidata_identity.parse_entity(entity, platform="instagram", handle="x")
    assert parsed is not None
    assert parsed["github_url"] is None
    entity["claims"]["P2037"][0]["mainsnak"]["datavalue"]["value"] = "pricing"
    parsed = wikidata_identity.parse_entity(entity, platform="instagram", handle="x")
    assert parsed["github_url"] is None
    entity["claims"]["P2037"][0]["mainsnak"]["datavalue"]["value"] = "octocat"
    parsed = wikidata_identity.parse_entity(entity, platform="instagram", handle="x")
    assert parsed["github_url"] == "https://github.com/octocat"


def test_soundcloud_claim_rejects_tracks_and_reserved_paths():
    entity = {
        "id": "Q1",
        "labels": {"en": {"value": "X"}},
        "claims": {
            "P2003": [{"mainsnak": {"datavalue": {"value": "x"}}}],
            "P3040": [{"mainsnak": {"datavalue": {"value": "forss/arigato"}}}],
        },
    }
    parsed = wikidata_identity.parse_entity(entity, platform="instagram", handle="x")
    assert parsed is not None
    assert parsed["soundcloud_url"] is None
    entity["claims"]["P3040"][0]["mainsnak"]["datavalue"]["value"] = "discover"
    parsed = wikidata_identity.parse_entity(entity, platform="instagram", handle="x")
    assert parsed["soundcloud_url"] is None
    entity["claims"]["P3040"][0]["mainsnak"]["datavalue"]["value"] = "forss"
    parsed = wikidata_identity.parse_entity(entity, platform="instagram", handle="x")
    assert parsed["soundcloud_url"] == "https://soundcloud.com/forss"


def test_wikidata_followers_without_platform_qualifier_are_ignored():
    entity = {
        "id": "Q1",
        "labels": {"en": {"value": "X"}},
        "claims": {
            "P2003": [{"mainsnak": {"datavalue": {"value": "x"}}}],
            "P8687": [{
                "mainsnak": {"datavalue": {"value": {"amount": "+12", "unit": "1"}}},
            }],
        },
    }
    parsed = wikidata_identity.parse_entity(entity, platform="instagram", handle="x")
    assert parsed is not None
    assert parsed["followers"] is None


def test_from_wikidata_accepts_official_homepage():
    ok = verify.from_wikidata("website", "https://www.figuringout.co/")
    assert ok.accept and ok.source == "wikidata"
    yt = verify.from_wikidata(
        "youtube", "https://www.youtube.com/channel/UC1234567890123456789012")
    assert yt.accept
    bad = verify.from_wikidata("youtube", "https://www.youtube.com/")
    assert not bad.accept
    tt = verify.from_wikidata("tiktok", "https://www.tiktok.com/@democreator")
    assert tt.accept and tt.source == "wikidata"
    rd = verify.from_wikidata("reddit", "https://www.reddit.com/user/democreator")
    assert rd.accept and rd.source == "wikidata"
    pod = verify.from_wikidata(
        "podcast", "https://podcasts.apple.com/podcast/id1530805412")
    assert pod.accept and pod.source == "wikidata"
    sky = verify.from_wikidata(
        "bluesky", "https://bsky.app/profile/democreator.bsky.social")
    assert sky.accept and sky.source == "wikidata"
    sky_post = verify.from_wikidata(
        "bluesky", "https://bsky.app/profile/democreator.bsky.social/post/3kabc")
    assert not sky_post.accept
    masto = verify.from_wikidata(
        "mastodon", "https://mastodon.social/@democreator")
    assert masto.accept and masto.source == "wikidata"
    masto_bare = verify.from_wikidata("mastodon", "https://mastodon.social/")
    assert not masto_bare.accept
    gh = verify.from_wikidata("github", "https://github.com/octocat")
    assert gh.accept and gh.source == "wikidata"
    gh_bare = verify.from_wikidata("github", "https://github.com/")
    assert not gh_bare.accept
    gh_repo = verify.from_wikidata("github", "https://github.com/octocat/repo")
    assert not gh_repo.accept
    gh_pricing = verify.from_wikidata("github", "https://github.com/pricing")
    assert not gh_pricing.accept
    sc = verify.from_wikidata("soundcloud", "https://soundcloud.com/forss")
    assert sc.accept and sc.source == "wikidata"
    sc_bare = verify.from_wikidata("soundcloud", "https://soundcloud.com/")
    assert not sc_bare.accept
    sc_track = verify.from_wikidata("soundcloud", "https://soundcloud.com/forss/track")
    assert not sc_track.accept
    sc_discover = verify.from_wikidata("soundcloud", "https://soundcloud.com/discover")
    assert not sc_discover.accept
    pin = verify.from_wikidata("pinterest", "https://www.pinterest.com/democreator/")
    assert pin.accept and pin.source == "wikidata"
    pin_pin = verify.from_wikidata("pinterest", "https://www.pinterest.com/pin/123/")
    assert not pin_pin.accept
    hn = verify.from_wikidata(
        "hackernews", "https://news.ycombinator.com/user?id=pg")
    assert hn.accept and hn.source == "wikidata"
    hn_item = verify.from_wikidata(
        "hackernews", "https://news.ycombinator.com/item?id=1")
    assert not hn_item.accept


def test_apply_keyless_identity_fills_name_and_wikidata_followers():
    raw = RawProfile(seed_url="https://www.instagram.com/democreator/",
                     seed_platform="instagram", seed_handle="democreator",
                     display_name="democreator")
    acc = PlatformAccount(platform="instagram", handle="democreator",
                          url="https://www.instagram.com/democreator/",
                          followers=None)
    kl = keyless.KeylessFindings(
        display_name="Demo Creator", wikidata_id="Q123",
        wikidata_followers=9_600_000, wikidata_followers_as_of="2024-06-01",
        wikidata_followers_platform="instagram")
    _apply_keyless_identity(raw, acc, kl, "instagram", "democreator")
    assert raw.display_name == "Demo Creator"
    assert acc.followers == 9_600_000
    assert acc.raw["followers_source"] == "wikidata"
    assert "Wikidata" in acc.errors[0]


def test_apply_keyless_identity_does_not_overwrite_instagram_count():
    raw = RawProfile(seed_url="https://www.instagram.com/democreator/",
                     seed_platform="instagram", seed_handle="democreator",
                     display_name="Demo Creator")
    acc = PlatformAccount(platform="instagram", handle="democreator",
                          url="https://www.instagram.com/democreator/",
                          followers=14_723_456, raw={"followers_source": "json"})
    kl = keyless.KeylessFindings(
        display_name="Demo Creator", wikidata_followers=9_600_000,
        wikidata_followers_platform="instagram")
    _apply_keyless_identity(raw, acc, kl, "instagram", "democreator")
    assert acc.followers == 14_723_456
    assert acc.raw["followers_source"] == "json"


def test_apply_wikidata_followers_fills_other_surfaces_only():
    raw = RawProfile(seed_url="https://www.instagram.com/democreator/",
                     seed_platform="instagram", seed_handle="democreator")
    ig = PlatformAccount(platform="instagram", handle="democreator",
                         url="https://www.instagram.com/democreator/",
                         followers=14_723_456, raw={"followers_source": "json"})
    yt = PlatformAccount(platform="youtube", handle="UC1234567890123456789012",
                         url="https://www.youtube.com/channel/UC1234567890123456789012",
                         followers=None)
    raw.accounts = [ig, yt]
    kl = keyless.KeylessFindings(wikidata_id="Q123", follower_readings=[
        {"platform": "instagram", "count": 9_600_000, "as_of": "2024-06-01"},
        {"platform": "youtube", "count": 5_000_000, "as_of": "2024-01-01"},
    ])
    _apply_wikidata_followers(raw, kl)
    assert ig.followers == 14_723_456
    assert yt.followers == 5_000_000
    assert yt.raw["followers_source"] == "wikidata"
    assert "Wikidata" in yt.errors[0]


def test_overview_uses_wikipedia_when_no_bio():
    raw = RawProfile(
        seed_url="https://www.instagram.com/democreator/",
        seed_platform="instagram", seed_handle="democreator",
        display_name="Demo Creator",
        keyless={
            "wikipedia_title": "Demo Creator",
            "wikipedia_extract": "Indian podcaster and entrepreneur.",
            "occupations": ["podcaster"],
            "citizenships": ["India"],
            "education": ["IIM Ahmedabad"],
            "awards": ["Forbes 30 Under 30"],
            "notable_works": ["Figuring Out"],
            "employers": ["House of Things"],
            "work_locations": ["Mumbai"],
            "positions": ["chief executive officer"],
            "residences": ["Delhi"],
            "birth_places": ["Lucknow"],
            "pseudonyms": ["Demo Show"],
            "official_names": ["Figuring Out Media"],
            "orcid": "0000-0002-1825-0097",
            "significant_events": ["IPO"],
            "fields_of_work": ["podcasting"],
            "genres": ["interview"],
            "languages": ["English", "Hindi"],
            "nominations": ["Filmfare Award"],
            "participations": ["TedX"],
            "memberships": ["TiE"],
            "wikipedia_categories": ["Indian podcasters"],
            "wikipedia_sections": [
                {"title": "Early life", "extract": "Born in India."},
                {"title": "Career", "extract": "Hosts Figuring Out."},
            ],
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Demo.jpg",
            "image_source": "wikipedia_summary",
        },
    )
    report = build(raw, "wiki-fallback")
    assert report.overview is not None
    assert "Wikipedia" in report.overview.positioning
    assert "Indian podcaster" in report.overview.positioning
    assert "IIM Ahmedabad (Wikidata education)" in report.overview.credentials
    assert "podcaster (Wikidata)" in report.overview.credentials
    assert report.overview.base_location == "Mumbai (Wikidata work location)"
    assert "Position: chief executive officer (Wikidata)" in report.overview.press
    assert "chief executive officer (Wikidata)" not in report.overview.credentials
    assert "Also known as: Demo Show (Wikidata pseudonym)" in report.overview.press
    assert "Official name: Figuring Out Media (Wikidata)" in report.overview.press
    assert "ORCID: 0000-0002-1825-0097 (Wikidata)" in report.overview.press
    assert "Significant event: IPO (Wikidata)" in report.overview.press
    assert "Born: Lucknow (Wikidata)" in report.overview.press
    assert "Demo Show" not in report.overview.credentials
    assert "Lucknow" not in (report.overview.base_location or "")
    assert "Delhi" not in (report.overview.base_location or "")
    assert "Award: Forbes 30 Under 30 (Wikidata)" in report.overview.press
    assert "Notable work: Figuring Out (Wikidata)" in report.overview.press
    assert "Employer: House of Things (Wikidata)" in report.overview.press
    assert "Figuring Out" not in report.overview.product_stack
    assert "podcasting (Wikidata field of work)" in report.overview.content_pillars
    assert "interview (Wikidata genre)" in report.overview.content_pillars
    assert "Indian podcasters (Wikipedia category)" in report.overview.content_pillars
    assert "Languages: English, Hindi (Wikidata)" in report.overview.press
    assert "Nominated for: Filmfare Award (Wikidata)" in report.overview.press
    assert "Participant: TedX (Wikidata)" in report.overview.press
    assert "Member of: TiE (Wikidata)" in report.overview.press
    assert "TiE (Wikidata)" not in report.overview.credentials
    assert not any("Early life" in x for x in report.overview.content_pillars)
    assert not any("Career" in x for x in report.overview.content_pillars)
    assert report.overview.portrait_url.endswith("Demo.jpg")
    assert report.overview.portrait_source == "wikipedia_summary"
    fake_ig = RawProfile(
        seed_url="https://www.instagram.com/democreator/",
        seed_platform="instagram", seed_handle="democreator",
        keyless={"image_url": "https://scontent.cdninstagram.com/v/t51.2885-19/x.jpg",
                 "image_source": "instagram"},
    )
    fake_report = build(fake_ig, "ig-cdn-rejected")
    assert fake_report.overview is not None
    assert not fake_report.overview.portrait_url


def test_overview_citizenship_only_when_no_work_location():
    raw = RawProfile(
        seed_url="https://www.instagram.com/democreator/",
        seed_platform="instagram", seed_handle="democreator",
        keyless={"citizenships": ["India"]},
    )
    report = build(raw, "citizenship-only")
    assert report.overview is not None
    assert report.overview.base_location == "India (Wikidata citizenship)"


def test_overview_residence_beats_citizenship_not_work_location():
    raw = RawProfile(
        seed_url="https://www.instagram.com/democreator/",
        seed_platform="instagram", seed_handle="democreator",
        keyless={"residences": ["Delhi"], "citizenships": ["India"]},
    )
    report = build(raw, "residence-fallback")
    assert report.overview is not None
    assert report.overview.base_location == "Delhi (Wikidata residence)"
    both = RawProfile(
        seed_url="https://www.instagram.com/democreator/",
        seed_platform="instagram", seed_handle="democreator",
        keyless={"work_locations": ["Mumbai"], "residences": ["Delhi"],
                 "citizenships": ["India"]},
    )
    both_report = build(both, "work-beats-residence")
    assert both_report.overview is not None
    assert both_report.overview.base_location == "Mumbai (Wikidata work location)"


def test_orcid_and_official_name_filters():
    assert wikidata_identity.orcid_from("0000-0002-1825-0097") == "0000-0002-1825-0097"
    assert wikidata_identity.orcid_from(
        "https://orcid.org/0000-0002-1825-0097") == "0000-0002-1825-0097"
    assert wikidata_identity.orcid_from("democreator") == ""
    entity = {
        "id": "Q1",
        "labels": {"en": {"value": "Demo Creator"}},
        "claims": {
            "P2003": [{"mainsnak": {"datavalue": {"value": "x"}}}],
            "P1448": [{"mainsnak": {"datavalue": {"value": "Demo Creator"}}}],
            "P496": [{"mainsnak": {"datavalue": {"value": "not-an-orcid"}}}],
            "P434": [{"mainsnak": {"datavalue": {"value": "not-an-mbid"}}}],
            "P3836": [{"mainsnak": {"datavalue": {"value": "pin"}}}],
            "P7171": [{"mainsnak": {"datavalue": {"value": "this-name-is-too-long-for-hn"}}}],
        },
    }
    parsed = wikidata_identity.parse_entity(entity, platform="instagram", handle="x")
    assert parsed is not None
    assert parsed["official_names"] == []
    assert parsed["orcid"] is None
    assert parsed["musicbrainz_id"] is None
    assert parsed["pinterest_url"] is None
    assert parsed["hackernews_url"] is None


def test_pseudonym_rejects_item_label():
    entity = {
        "id": "Q1",
        "labels": {"en": {"value": "Demo Creator"}},
        "claims": {
            "P2003": [{"mainsnak": {"datavalue": {"value": "x"}}}],
            "P742": [{"mainsnak": {"datavalue": {"value": "Demo Creator"}}}],
        },
    }
    parsed = wikidata_identity.parse_entity(entity, platform="instagram", handle="x")
    assert parsed is not None
    assert parsed["pseudonyms"] == []


def test_overview_birthplace_is_not_base_location():
    raw = RawProfile(
        seed_url="https://www.instagram.com/democreator/",
        seed_platform="instagram", seed_handle="democreator",
        keyless={"birth_places": ["Lucknow"], "pseudonyms": ["Demo Show"]},
    )
    report = build(raw, "birthplace-not-base")
    assert report.overview is not None
    assert not report.overview.base_location
    assert "Born: Lucknow (Wikidata)" in report.overview.press
    assert "Also known as: Demo Show (Wikidata pseudonym)" in report.overview.press
    with_citizenship = RawProfile(
        seed_url="https://www.instagram.com/democreator/",
        seed_platform="instagram", seed_handle="democreator",
        keyless={"birth_places": ["Lucknow"], "citizenships": ["India"]},
    )
    cited = build(with_citizenship, "birthplace-not-citizenship")
    assert cited.overview is not None
    assert cited.overview.base_location == "India (Wikidata citizenship)"
    assert "Lucknow" not in (cited.overview.base_location or "")


def test_title_pillars_need_two_titles():
    assert recurring_title_tokens(["How to start a business"]) == []
    assert recurring_title_tokens([
        "How to start a business",
        "Business ideas that work",
        "One-off cooking vlog",
    ]) == ["business"]
    acc = PlatformAccount(platform="youtube", handle="x",
                          url="https://www.youtube.com/@x")
    acc.content = [
        ContentItem(platform="youtube", title="How to start a business"),
        ContentItem(platform="youtube", title="Business ideas that work"),
    ]
    raw = RawProfile(
        seed_url="https://www.instagram.com/x/",
        seed_platform="instagram", seed_handle="x",
        accounts=[acc],
    )
    report = build(raw, "title-pillars")
    assert "business (from published titles)" in report.overview.content_pillars


def test_wikipedia_sections_drop_references_and_empty_heads():
    parsed = keyless.parse_plaintext_article(
        "Indian podcaster and entrepreneur.\n"
        "== Early life ==\n"
        "Born in India.\n"
        "=== School ===\n"
        "Went to school.\n"
        "== Career ==\n"
        "Hosts Figuring Out.\n"
        "== References ==\n"
        "* citation\n"
        "== See also ==\n"
        "Other people.\n"
    )
    assert parsed["extract"].startswith("Indian podcaster")
    titles = [row["title"] for row in parsed["sections"]]
    assert titles == ["Early life", "Career"]
    assert "school" in parsed["sections"][0]["extract"].lower()
    assert keyless.parse_plaintext_article("") == {"extract": "", "sections": []}
    assert keyless.parse_extracts({
        "query": {"pages": {"1": {"extract": "== Career ==\nHosts a show."}}},
    }).startswith("== Career ==")
    assert keyless.parse_extracts({"query": {"pages": {}}}) == ""


def test_wikipedia_categories_skip_living_people():
    cats = keyless.parse_categories({
        "query": {"pages": {"1": {"categories": [
            {"title": "Category:Living people"},
            {"title": "Category:1995 births"},
            {"title": "Category:Indian podcasters"},
            {"title": "Category:CS1 maint"},
        ]}}},
    })
    assert cats == ["Indian podcasters"]


def test_item_qids_ignore_plain_strings():
    entity = {
        "claims": {
            "P106": [
                {"mainsnak": {"datavalue": {"value": "podcaster"}}},
                {"mainsnak": {"datavalue": {"value": {"id": "Q33999"}}}},
            ],
        },
    }
    assert wikidata_identity.item_qids(entity, "P106") == ["Q33999"]


def test_overview_hydrates_official_records_without_inventing_metrics():
    raw = RawProfile(
        seed_url="https://www.instagram.com/democreator/",
        seed_platform="instagram", seed_handle="democreator",
        keyless={
            "orcid": "0000-0002-1825-0097",
            "orcid_record": {
                "biography": "Public ORCID bio.",
                "employments": ["Host at House of Things"],
                "educations": ["IIM Ahmedabad"],
                "works": ["Figuring Out"],
            },
            "pageviews": {"article": "Demo Creator", "days": 30, "views": 12345,
                          "latest_day": 400},
            "musicbrainz": {"name": "Demo Creator", "type": "Person",
                            "country": "IN", "homepage": "https://www.figuringout.co/"},
            "spotify_artist": {"title": "Demo Creator",
                               "thumbnail": "https://i.scdn.co/image/abc"},
        },
    )
    report = build(raw, "public-records")
    assert report.overview is not None
    assert "ORCID biography" in report.overview.positioning
    assert "IIM Ahmedabad (ORCID education)" in report.overview.credentials
    assert "Employment: Host at House of Things (ORCID)" in report.overview.press
    assert "Work: Figuring Out (ORCID)" in report.overview.press
    assert "Figuring Out" not in report.overview.product_stack
    assert "Host at House of Things" not in report.overview.credentials
    assert "Wikipedia pageviews: 12,345 in 30 days" in " ".join(report.overview.press)
    assert "not site traffic or followers" in " ".join(report.overview.press)
    assert "MusicBrainz: Demo Creator (Person)" in report.overview.press
    assert "MusicBrainz country listing: IN" in " ".join(report.overview.press)
    assert "IN" not in (report.overview.base_location or "")
    assert "Spotify artist: Demo Creator (oEmbed, not listeners)" in report.overview.press
    assert not report.overview.portrait_url
