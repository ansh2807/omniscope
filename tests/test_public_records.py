"""Official public-record hydration — IDs we already have, never guessed."""
from __future__ import annotations

from datetime import datetime, timezone

from app.engine.discovery import public_records as rec
from app.engine.discovery.wikidata_identity import musicbrainz_id


def test_musicbrainz_and_spotify_ids_reject_guesses():
    assert rec.musicbrainz_id("a74b1b7f-71a5-4011-9441-d0b5e4122711")
    assert rec.musicbrainz_id(
        "https://musicbrainz.org/artist/a74b1b7f-71a5-4011-9441-d0b5e4122711")
    assert rec.musicbrainz_id("democreator") == ""
    assert rec.musicbrainz_id("not-a-uuid") == ""
    assert musicbrainz_id("a74b1b7f-71a5-4011-9441-d0b5e4122711")
    assert rec.spotify_artist_id(
        "https://open.spotify.com/artist/1abcSpotifyId22xxxxxxx") == "1abcSpotifyId22xxxxxxx"
    assert rec.spotify_artist_id(
        "https://open.spotify.com/show/abcdefghij0123456789ab") == ""
    assert rec.spotify_artist_id("democreator") == ""


def test_parse_orcid_copies_affiliations_and_work_titles():
    parsed = rec.parse_orcid({
        "person": {
            "name": {
                "given-names": {"value": "Josiah"},
                "family-name": {"value": "Carberry"},
            },
            "biography": {"content": "Psychoceramics."},
        },
        "activities-summary": {
            "employments": {"affiliation-group": [{
                "summaries": [{"employment-summary": {
                    "role-title": "Professor",
                    "organization": {"name": "Brown University"},
                }}],
            }]},
            "educations": {"affiliation-group": [{
                "summaries": [{"education-summary": {
                    "organization": {"name": "Brown University"},
                }}],
            }]},
            "works": {"group": [{
                "work-summary": [{
                    "title": {"title": {"value": "The geology of psychoceramics"}},
                }],
            }]},
        },
    })
    assert parsed["display_name"] == "Josiah Carberry"
    assert parsed["biography"] == "Psychoceramics."
    assert parsed["employments"] == ["Professor at Brown University"]
    assert parsed["educations"] == ["Brown University"]
    assert parsed["works"] == ["The geology of psychoceramics"]
    assert rec.parse_orcid({}) == {}
    assert rec.parse_orcid({"person": {}}) == {}


def test_parse_pageviews_sums_days_and_ignores_junk():
    parsed = rec.parse_pageviews({
        "items": [
            {"article": "Demo_Creator", "views": 100, "timestamp": "2026080100"},
            {"article": "Demo_Creator", "views": 50, "timestamp": "2026080200"},
            {"article": "Demo_Creator", "views": "nope"},
        ],
    })
    assert parsed["article"] == "Demo Creator"
    assert parsed["days"] == 2
    assert parsed["views"] == 150
    assert parsed["latest_day"] == 50
    assert rec.parse_pageviews({"items": []}) == {}
    assert rec.parse_pageviews({}) == {}


def test_pageviews_url_uses_underscores_and_daily_window():
    url = rec.pageviews_url(
        "Demo Creator", days=30,
        now=datetime(2026, 8, 22, tzinfo=timezone.utc))
    assert "Demo_Creator" in url
    assert "/daily/20260723/20260822" in url
    assert rec.pageviews_url("") == ""


def test_parse_musicbrainz_keeps_homepage_drops_empty_name():
    parsed = rec.parse_musicbrainz({
        "name": "Demo Creator",
        "type": "Person",
        "country": "IN",
        "relations": [
            {"type": "social network",
             "url": {"resource": "https://www.instagram.com/democreator/"}},
            {"type": "official homepage",
             "url": {"resource": "https://www.figuringout.co/"}},
        ],
    })
    assert parsed["name"] == "Demo Creator"
    assert parsed["type"] == "Person"
    assert parsed["country"] == "IN"
    assert parsed["homepage"] == "https://www.figuringout.co/"
    assert rec.parse_musicbrainz({"type": "Person"}) == {}


def test_parse_spotify_oembed_is_title_only():
    parsed = rec.parse_spotify_oembed({
        "title": "Demo Creator",
        "thumbnail_url": "https://i.scdn.co/image/abc",
        "provider_name": "Spotify",
    })
    assert parsed == {"title": "Demo Creator",
                      "thumbnail": "https://i.scdn.co/image/abc"}
    assert rec.parse_spotify_oembed({"thumbnail_url": "https://i.scdn.co/image/abc"}) == {}
