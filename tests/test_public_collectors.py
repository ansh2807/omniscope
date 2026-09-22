"""Public Reddit / TikTok / podcast / site-feed / Telegram collectors — no invented metrics."""
from __future__ import annotations

from types import SimpleNamespace

from app.engine.assemble import build
from app.engine.collectors import bluesky as bsky
from app.engine.collectors import github as gh
from app.engine.collectors import hackernews as hn
from app.engine.collectors import mastodon as masto
from app.engine.collectors import pinterest as pin
from app.engine.collectors import soundcloud as sc
from app.engine.collectors import podcast as pod
from app.engine.collectors import reddit as reddit_col
from app.engine.collectors import tiktok as tt
from app.engine.collectors import web
from app.engine.resolver import resolve
from app.omni.feeds import FeedItem
from app.omni.input_resolver import KIND_CREATOR, KIND_POST, classify
from app.schemas import PlatformAccount, RawProfile, Testimonial


ABOUT = {
    "kind": "t2",
    "data": {
        "name": "democreator",
        "total_karma": 12_000,
        "link_karma": 8_000,
        "comment_karma": 4_000,
        "subreddit": {
            "title": "Demo Creator",
            "public_description": "Figuring Out",
            "subscribers": 1500,
        },
    },
}

SUBMITTED = {
    "data": {
        "children": [{
            "kind": "t3",
            "data": {
                "title": "New episode",
                "permalink": "/r/podcasts/comments/abc/new_episode/",
                "score": 42,
                "num_comments": 7,
                "created_utc": 1_717_200_000,
            },
        }],
    },
}

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Figuring Out</title>
    <description>Conversations.</description>
    <item>
      <title>How to start</title>
      <link>https://example.com/ep1</link>
      <pubDate>Sat, 01 Jun 2024 12:00:00 GMT</pubDate>
      <itunes:duration>01:02:03</itunes:duration>
    </item>
    <item>
      <title>Second talk</title>
      <pubDate>Wed, 01 May 2024 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def test_reddit_karma_is_not_followers():
    parsed = reddit_col.parse_about(ABOUT)
    assert parsed["name"] == "democreator"
    assert parsed["followers"] == 1500
    assert parsed["total_karma"] == 12_000
    about_no_subs = {
        "data": {"name": "x", "total_karma": 99, "subreddit": {"title": "x"}},
    }
    assert reddit_col.parse_about(about_no_subs)["followers"] is None
    assert reddit_col.parse_about(about_no_subs)["total_karma"] == 99


def test_reddit_submitted_score_is_votes_not_views():
    posts = reddit_col.parse_submitted(SUBMITTED)
    assert len(posts) == 1
    assert posts[0]["title"] == "New episode"
    assert posts[0]["likes"] == 42
    assert posts[0]["comments"] == 7
    assert posts[0]["url"].endswith("/new_episode/")
    assert "views" not in posts[0]
    assert posts[0]["published_at"] is not None
    assert reddit_col.parse_submitted({}) == []


def test_tiktok_oembed_has_no_follower_field():
    fields = tt.parse_oembed({
        "author_name": "Demo Creator",
        "title": "democreator on TikTok",
        "author_url": "https://www.tiktok.com/@democreator",
        "thumbnail_url": "https://example.com/t.jpg",
    })
    assert fields["display_name"] == "Demo Creator"
    assert fields["title"] == "democreator on TikTok"
    assert "followers" not in fields
    assert "views" not in fields
    assert tt.parse_oembed({}) == {}
    assert "tiktok.com/oembed" in tt.oembed_url("https://www.tiktok.com/@democreator")


def test_podcast_rss_copies_titles_not_listens():
    parsed = pod.parse_rss(RSS)
    assert parsed["title"] == "Figuring Out"
    assert len(parsed["items"]) == 2
    first, second = parsed["items"]
    assert first["title"] == "How to start"
    assert first["url"] == "https://example.com/ep1"
    assert first["duration_seconds"] == 3723
    assert first["published_at"] is not None
    assert "views" not in first
    assert second["title"] == "Second talk"
    assert second["duration_seconds"] is None
    assert pod.parse_rss("<not xml")["items"] == []


def test_podcast_lookup_uses_apple_track_count_only():
    meta = pod.parse_lookup({
        "results": [{
            "collectionName": "Figuring Out",
            "artistName": "Demo Creator",
            "feedUrl": "https://feeds.example.com/show.xml",
            "trackCount": 400,
            "collectionViewUrl": "https://podcasts.apple.com/podcast/id1530805412",
        }],
    })
    assert meta["title"] == "Figuring Out"
    assert meta["feed_url"] == "https://feeds.example.com/show.xml"
    assert meta["track_count"] == 400
    assert meta["apple_average_rating"] is None
    assert meta["apple_rating_count"] is None
    assert "followers" not in meta
    assert "rating_count" not in meta
    assert pod.parse_lookup({"results": []}) == {}
    assert pod.itunes_id_from(
        "https://podcasts.apple.com/in/podcast/figuring-out/id1530805412") == "1530805412"
    assert pod.spotify_show_id_from(
        "https://open.spotify.com/show/abcdefghij0123456789ab") == "abcdefghij0123456789ab"
    assert pod.spotify_show_id_from("https://open.spotify.com/artist/1abcSpotifyId22") == ""


def test_podcast_apple_reviews_are_not_listens():
    meta = pod.parse_lookup({
        "results": [{
            "collectionName": "Figuring Out",
            "trackCount": 400,
            "averageUserRating": 4.8,
            "userRatingCount": 12_000,
            "feedUrl": "https://feeds.example.com/show.xml",
        }],
    })
    assert meta["track_count"] == 400
    assert meta["apple_average_rating"] == 4.8
    assert meta["apple_rating_count"] == 12_000
    assert "followers" not in meta
    assert "rating_count" not in meta
    reviews = pod.parse_reviews({
        "feed": {"entry": [
            {"title": {"label": "Figuring Out"}, "im:name": {"label": "Figuring Out"}},
            {
                "author": {"name": {"label": "Asha"}},
                "title": {"label": "Loved it"},
                "content": {"label": "Best interviews."},
                "im:rating": {"label": "5"},
                "updated": {"label": "2024-06-01T12:00:00-07:00"},
            },
            {
                "title": {"label": "No stars"},
                "content": {"label": "skip me"},
            },
        ]},
    })
    assert len(reviews) == 1
    assert reviews[0]["author"] == "Asha"
    assert reviews[0]["rating"] == 5.0
    assert reviews[0]["text"] == "Best interviews."
    assert reviews[0]["dated"] == "2024-06-01"
    assert "views" not in reviews[0]
    assert pod.parse_reviews({}) == []
    assert "customerreviews" in pod.review_feed_url("1530805412")

    acc = PlatformAccount(
        platform="podcast", handle="1530805412",
        url="https://podcasts.apple.com/podcast/id1530805412")
    acc.testimonials = [
        Testimonial(text="Best interviews.", author="Asha", rating=5.0, dated="2024-06-01"),
    ]
    raw = RawProfile(
        seed_url="https://www.instagram.com/democreator/",
        seed_platform="instagram", seed_handle="democreator",
        accounts=[acc],
    )
    report = build(raw, "apple-reviews")
    assert report.sentiment["source_label"] == "Apple Podcasts customer reviews"
    assert "booking page" not in report.sentiment["scope_note"]
    assert "Apple Podcasts customer reviews" in report.sentiment["scope_note"]


def test_resolver_and_input_treat_show_urls_as_creator():
    apple = resolve("https://podcasts.apple.com/in/podcast/figuring-out/id1530805412")
    assert apple.platform == "podcast" and apple.handle == "1530805412"
    spotify = resolve("https://open.spotify.com/show/abcdefghij0123456789ab")
    assert spotify.platform == "podcast" and spotify.handle == "abcdefghij0123456789ab"
    reddit = resolve("https://www.reddit.com/user/democreator")
    assert reddit.platform == "reddit" and reddit.handle == "democreator"
    ui = classify("https://podcasts.apple.com/podcast/id1530805412")
    assert ui.kind == KIND_CREATOR and ui.platform == "podcast"
    sky = resolve("https://bsky.app/profile/democreator.bsky.social")
    assert sky.platform == "bluesky" and sky.handle == "democreator.bsky.social"
    sky_ui = classify("https://bsky.app/profile/democreator.bsky.social")
    assert sky_ui.kind == KIND_CREATOR and sky_ui.platform == "bluesky"
    masto = resolve("https://mastodon.social/@democreator")
    assert masto.platform == "mastodon" and masto.handle == "democreator@mastodon.social"
    masto_acct = resolve("democreator@mastodon.social")
    assert masto_acct.platform == "mastodon" and masto_acct.handle == "democreator@mastodon.social"
    masto_ui = classify("https://fosstodon.org/@democreator")
    assert masto_ui.kind == KIND_CREATOR and masto_ui.platform == "mastodon"
    medium = resolve("https://medium.com/@democreator")
    assert medium.platform == "website"
    email = resolve("democreator@gmail.com")
    assert email.platform != "mastodon"
    github = resolve("https://github.com/octocat")
    assert github.platform == "github" and github.handle == "octocat"
    github_ui = classify("https://github.com/octocat")
    assert github_ui.kind == KIND_CREATOR and github_ui.platform == "github"
    github_repo = resolve("https://github.com/octocat/Hello-World")
    assert github_repo.platform == "website"
    github_pricing = resolve("https://github.com/pricing")
    assert github_pricing.platform == "website"
    sound = resolve("https://soundcloud.com/forss")
    assert sound.platform == "soundcloud" and sound.handle == "forss"
    sound_ui = classify("https://soundcloud.com/forss")
    assert sound_ui.kind == KIND_CREATOR and sound_ui.platform == "soundcloud"
    sound_track = resolve("https://soundcloud.com/forss/arigato")
    assert sound_track.platform == "website"
    sound_discover = resolve("https://soundcloud.com/discover")
    assert sound_discover.platform == "website"
    pins = resolve("https://www.pinterest.com/democreator/")
    assert pins.platform == "pinterest" and pins.handle == "democreator"
    pins_ui = classify("https://www.pinterest.com/democreator/")
    assert pins_ui.kind == KIND_CREATOR and pins_ui.platform == "pinterest"
    pin_item = resolve("https://www.pinterest.com/pin/123456/")
    assert pin_item.platform == "website"
    pin_post = classify("https://www.pinterest.com/pin/123456/")
    assert pin_post.kind == KIND_POST
    news = resolve("https://news.ycombinator.com/user?id=pg")
    assert news.platform == "hackernews" and news.handle == "pg"
    news_ui = classify("https://news.ycombinator.com/user?id=pg")
    assert news_ui.kind == KIND_CREATOR and news_ui.platform == "hackernews"
    news_item = resolve("https://news.ycombinator.com/item?id=1")
    assert news_item.platform == "website"


def test_bluesky_profile_likes_are_not_views():
    prof = bsky.parse_profile({
        "handle": "democreator.bsky.social",
        "displayName": "Demo Creator",
        "description": "Figuring Out",
        "did": "did:plc:abc",
        "followersCount": 1200,
        "followsCount": 10,
        "postsCount": 40,
    })
    assert prof["followers"] == 1200
    assert prof["posts"] == 40
    assert "views" not in prof
    posts = bsky.parse_feed({
        "feed": [{
            "post": {
                "uri": "at://did:plc:abc/app.bsky.feed.post/3kabc",
                "likeCount": 9,
                "replyCount": 2,
                "record": {
                    "text": "New episode is live",
                    "createdAt": "2024-06-01T12:00:00.000Z",
                },
            },
        }],
    }, handle="democreator.bsky.social")
    assert len(posts) == 1
    assert posts[0]["likes"] == 9
    assert posts[0]["comments"] == 2
    assert "views" not in posts[0]
    assert posts[0]["url"].endswith("/post/3kabc")
    assert bsky.parse_profile({}) == {}
    assert bsky.parse_feed({}, handle="x") == []


def test_mastodon_favourites_are_not_views():
    assert masto.parse_acct("democreator@mastodon.social") == (
        "democreator", "mastodon.social")
    assert masto.parse_acct("https://mastodon.social/@democreator") == (
        "democreator", "mastodon.social")
    assert masto.parse_acct("https://medium.com/@democreator") == ("", "")
    assert masto.parse_acct("democreator") == ("", "")
    assert masto.parse_acct("democreator@gmail.com") == ("", "")
    assert masto.parse_acct("democreator@gmail.com", loose=False) == ("", "")
    assert masto.profile_from_claim("democreator@mastodon.social") == (
        "https://mastodon.social/@democreator")
    assert masto.profile_from_claim("democreator") == ""
    prof = masto.parse_profile({
        "id": "123",
        "acct": "democreator",
        "display_name": "Demo Creator",
        "note": "<p>Figuring Out</p>",
        "followers_count": 1200,
        "following_count": 10,
        "statuses_count": 40,
        "url": "https://mastodon.social/@democreator",
    })
    assert prof["followers"] == 1200
    assert prof["posts"] == 40
    assert "views" not in prof
    posts = masto.parse_statuses([{
        "content": "<p>New episode is live</p>",
        "url": "https://mastodon.social/@democreator/111",
        "favourites_count": 9,
        "replies_count": 2,
        "reblogs_count": 4,
        "created_at": "2024-06-01T12:00:00.000Z",
    }])
    assert len(posts) == 1
    assert posts[0]["likes"] == 9
    assert posts[0]["comments"] == 2
    assert "views" not in posts[0]
    assert posts[0]["title"] == "New episode is live"
    assert masto.parse_profile({}) == {}
    assert masto.parse_statuses([]) == []


def test_github_stars_are_not_views():
    assert gh.username_from("octocat") == "octocat"
    assert gh.username_from("https://github.com/octocat") == "octocat"
    assert gh.username_from("https://github.com/octocat/Hello-World") == ""
    assert gh.username_from("https://github.com/pricing") == ""
    assert gh.username_from("democreator") == "democreator"
    prof = gh.parse_profile({
        "login": "octocat",
        "name": "The Octocat",
        "bio": "GitHub mascot",
        "html_url": "https://github.com/octocat",
        "followers": 4000,
        "following": 9,
        "public_repos": 8,
    })
    assert prof["followers"] == 4000
    assert prof["posts"] == 8
    assert "views" not in prof
    repos = gh.parse_repos([
        {
            "name": "Hello-World",
            "description": "My first repository",
            "html_url": "https://github.com/octocat/Hello-World",
            "stargazers_count": 99,
            "fork": False,
            "updated_at": "2024-06-01T12:00:00Z",
        },
        {
            "name": "forked-app",
            "description": "not owned",
            "html_url": "https://github.com/octocat/forked-app",
            "stargazers_count": 50,
            "fork": True,
        },
    ])
    assert len(repos) == 1
    assert repos[0]["title"].startswith("Hello-World")
    assert "views" not in repos[0]
    assert "likes" not in repos[0]
    assert "stargazers" not in repos[0]
    assert gh.parse_profile({}) == {}
    assert gh.parse_repos([]) == []


def test_soundcloud_oembed_has_no_plays():
    assert sc.username_from("forss") == "forss"
    assert sc.username_from("https://soundcloud.com/forss") == "forss"
    assert sc.username_from("https://soundcloud.com/forss/arigato") == ""
    assert sc.username_from("https://soundcloud.com/discover") == ""
    fields = sc.parse_oembed({
        "author_name": "Forss",
        "title": "Forss",
        "description": "Stockholm",
        "author_url": "https://soundcloud.com/forss",
        "thumbnail_url": "https://i1.sndcdn.com/avatars-000.jpg",
        "playback_count": 99,
        "follower_count": 12,
    })
    assert fields["display_name"] == "Forss"
    assert fields["bio"] == "Stockholm"
    assert "views" not in fields
    assert "followers" not in fields
    assert "playback_count" not in fields
    assert sc.parse_oembed({}) == {}


def test_pinterest_oembed_has_no_followers():
    assert pin.username_from("democreator") == "democreator"
    assert pin.username_from("https://www.pinterest.com/democreator/") == "democreator"
    assert pin.username_from("https://www.pinterest.com/pin/123456/") == ""
    assert pin.username_from("https://www.pinterest.com/ideas/") == ""
    fields = pin.parse_oembed({
        "author_name": "Demo",
        "title": "Demo on Pinterest",
        "author_url": "https://www.pinterest.com/democreator/",
        "thumbnail_url": "https://i.pinimg.com/x.jpg",
        "follower_count": 99,
    })
    assert fields["display_name"] == "Demo"
    assert "followers" not in fields
    assert "follower_count" not in fields
    assert pin.parse_oembed({}) == {}


def test_hackernews_karma_is_not_followers():
    assert hn.username_from("pg") == "pg"
    assert hn.username_from("https://news.ycombinator.com/user?id=pg") == "pg"
    assert hn.username_from("https://news.ycombinator.com/item?id=1") == ""
    prof = hn.parse_user({
        "id": "pg",
        "about": "essays",
        "karma": 155000,
        "submitted": [1, 2, 3],
    })
    assert prof["posts"] == 3
    assert prof["karma"] == 155000
    assert "followers" not in prof
    story = hn.parse_item({
        "id": 1,
        "title": "Do things that don't scale",
        "score": 400,
        "time": 1173923446,
        "url": "https://paulgraham.com/ds.html",
    })
    assert story["title"].startswith("Do things")
    assert "views" not in story
    assert "score" not in story
    assert hn.parse_user({}) == {}
    assert hn.parse_item({"deleted": True, "title": "gone"}) == {}


TG_PREVIEW = """
<div class="tgme_widget_message" data-post="demo/10">
  <div class="tgme_widget_message_text">First episode drop</div>
  <span class="tgme_widget_message_views">12.3K</span>
  <a class="tgme_widget_message_date" href="https://t.me/demo/10">
    <time datetime="2024-06-01T12:00:00+00:00">1 Jun</time>
  </a>
</div>
<div class="tgme_widget_message" data-post="demo/11">
  <div class="tgme_widget_message_text">Second talk</div>
  <a class="tgme_widget_message_date" href="https://t.me/demo/11">
    <time datetime="2024-06-08T12:00:00+00:00">8 Jun</time>
  </a>
</div>
<div class="tgme_widget_message" data-post="demo/12">
  <a class="tgme_widget_message_photo" href="https://t.me/demo/12"></a>
</div>
"""


def test_website_feed_items_copy_titles_not_traffic():
    feed_rows = [
        FeedItem(title="How we pitch", url="https://acme.example/pitch",
                 published="2024-06-01", source_feed="https://acme.example/feed.xml"),
        FeedItem(title="", url="https://acme.example/empty", published="2024-06-02"),
        FeedItem(title="Dated only in the title 2024-01-01",
                 url="https://acme.example/x", published=""),
    ]
    items = web.content_from_feed_items(feed_rows)
    assert [row.title for row in items] == [
        "How we pitch", "Dated only in the title 2024-01-01"]
    assert items[0].views is None
    assert items[0].likes is None
    assert items[0].published_at is not None
    assert items[0].published_at.isoformat().startswith("2024-06-01")
    assert items[1].published_at is None
    assert items[0].raw["source"] == "advertised_rss_atom"

    acc = PlatformAccount(platform="website", url="https://acme.example", raw={})
    web._attach_site_feeds(acc, SimpleNamespace(
        items=feed_rows, feeds=["https://acme.example/feed.xml"], reason=""))
    assert acc.posts is None
    assert len(acc.content) == 2
    assert acc.content[0].published_at is not None
    assert acc.raw["feeds"] == ["https://acme.example/feed.xml"]


def test_website_feed_reason_without_invented_items():
    acc = PlatformAccount(platform="website", url="https://acme.example", raw={})
    web._attach_site_feeds(acc, SimpleNamespace(
        items=[], feeds=["https://acme.example/feed.xml"],
        reason="Feed response was not well-formed RSS or Atom XML."))
    assert acc.content == []
    assert acc.posts is None
    assert "well-formed" in acc.errors[-1]


def test_telegram_preview_copies_printed_text_not_channel_size():
    rows = web.parse_telegram_preview(TG_PREVIEW)
    assert len(rows) == 2
    assert rows[0]["title"] == "First episode drop"
    assert rows[0]["url"] == "https://t.me/demo/10"
    assert rows[0]["views"] == 12_300
    assert rows[0]["published_at"] is not None
    assert "views" not in rows[1]
    assert web.parse_telegram_preview("") == []
    assert web.parse_telegram_preview("<html><p>login</p></html>") == []
    assert web.day_from_iso("not-a-date") is None
    assert web.day_from_iso("") is None
