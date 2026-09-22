"""Public Instagram HTML parsing — no login, no invented counts."""
from __future__ import annotations

from app.engine.collectors.instagram import apply_public_html, parse_public_html
from app.schemas import PlatformAccount


def test_parses_classic_og_description_counts():
    html = '''<html><head>
    <meta property="og:title" content="Demo Creator (@democreator) • Instagram photos and videos">
    <meta property="og:description" content="9.6M Followers, 12 Following, 847 Posts - See Instagram photos and videos from Demo Creator (@democreator)">
    </head></html>'''
    d = parse_public_html(html)
    assert d["display_name"] == "Demo Creator"
    assert d["followers"] == 9_600_000
    assert d["following"] == 12
    assert d["posts"] == 847
    assert d["followers_source"] == "og_description"


def test_parses_reversed_meta_attributes_and_single_quotes():
    html = """<meta content='1.7M Followers, 80 Following, 412 Posts - See Instagram photos'
              property='og:description'>"""
    d = parse_public_html(html)
    assert d["followers"] == 1_700_000
    assert d["following"] == 80
    assert d["posts"] == 412


def test_json_counts_beat_rounded_og_description():
    html = '''<meta property="og:description" content="10M Followers, 1 Following, 1 Posts">
    <script>window._sharedData = {"entry_data":{"ProfilePage":[{"graphql":{"user":{
      "full_name":"Demo Creator",
      "biography":"Podcast host",
      "is_verified":true,
      "edge_followed_by":{"count":14723456},
      "edge_follow":{"count":18},
      "edge_owner_to_timeline_media":{"count":900}
    }}}]}}</script>'''
    d = parse_public_html(html)
    assert d["display_name"] == "Demo Creator"
    assert d["bio"] == "Podcast host"
    assert d["verified"] is True
    assert d["followers"] == 14_723_456
    assert d["following"] == 18
    assert d["posts"] == 900
    assert d["followers_source"] == "json"


def test_login_wall_without_counts_stays_empty():
    html = '''<html><body>
    <h1>Log in to continue</h1>
    <meta property="og:title" content="Instagram">
    </body></html>'''
    d = parse_public_html(html)
    assert d.get("followers") is None
    assert d.get("following") is None
    assert d.get("posts") is None


def test_apply_does_not_invent_a_follower_count():
    acc = PlatformAccount(platform="instagram", handle="democreator",
                          url="https://www.instagram.com/democreator/")
    apply_public_html(acc, "<html><body>Log in to continue</body></html>")
    assert acc.followers is None
