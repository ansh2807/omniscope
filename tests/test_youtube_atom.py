"""YouTube public Atom feed — titles and feed views only, no invented subscribers."""
from __future__ import annotations

from app.engine.collectors import youtube as yt


ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
 <title>Demo Creator</title>
 <yt:channelId>UC1234567890123456789012</yt:channelId>
 <entry>
  <yt:videoId>abcdefghijk</yt:videoId>
  <title>How to start</title>
  <published>2024-06-01T12:00:00+00:00</published>
  <media:group>
   <media:community>
    <media:statistics views="12345"/>
   </media:community>
  </media:group>
 </entry>
 <entry>
  <yt:videoId>lmnopqrstuv</yt:videoId>
  <title>Second talk</title>
  <published>2024-05-01T12:00:00+00:00</published>
 </entry>
</feed>
"""


def test_channel_id_from_handle_and_html():
    assert yt.channel_id_from("UC1234567890123456789012") == "UC1234567890123456789012"
    assert yt.channel_id_from("@democreator") == ""
    html = '{"externalId":"UC1234567890123456789012","title":"x"}'
    assert yt.channel_id_from("democreator", html) == "UC1234567890123456789012"


def test_parse_atom_feed_copies_views_and_leaves_missing_views_empty():
    parsed = yt.parse_atom_feed(ATOM)
    assert parsed["title"] == "Demo Creator"
    assert parsed["channel_id"] == "UC1234567890123456789012"
    assert len(parsed["videos"]) == 2
    first, second = parsed["videos"]
    assert first["title"] == "How to start"
    assert first["url"].endswith("abcdefghijk")
    assert first["views"] == 12_345
    assert first["published_at"] is not None
    assert second["title"] == "Second talk"
    assert second["views"] is None


def test_parse_atom_feed_rejects_garbage():
    assert yt.parse_atom_feed("<not xml")["videos"] == []
    assert yt.parse_atom_feed("<feed xmlns='http://www.w3.org/2005/Atom'></feed>")["videos"] == []
