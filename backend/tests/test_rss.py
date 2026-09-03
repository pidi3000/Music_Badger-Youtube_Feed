from app.services.rss import parse_uploads_feed

SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
 <link rel="self" href="http://www.youtube.com/feeds/videos.xml?channel_id=UC_x5XG1OV2P6uZZ5FSM9Ttw"/>
 <id>yt:channel:UC_x5XG1OV2P6uZZ5FSM9Ttw</id>
 <yt:channelId>UC_x5XG1OV2P6uZZ5FSM9Ttw</yt:channelId>
 <title>Example Channel</title>
 <link rel="alternate" href="https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw"/>
 <author>
  <name>Example Channel</name>
  <uri>https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw</uri>
 </author>
 <published>2007-05-14T16:04:00+00:00</published>
 <entry>
  <id>yt:video:abc123DEF45</id>
  <yt:videoId>abc123DEF45</yt:videoId>
  <yt:channelId>UC_x5XG1OV2P6uZZ5FSM9Ttw</yt:channelId>
  <title>First Video</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=abc123DEF45"/>
  <author>
   <name>Example Channel</name>
   <uri>https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw</uri>
  </author>
  <published>2024-01-15T18:00:00+00:00</published>
  <updated>2024-01-16T00:00:00+00:00</updated>
  <media:group>
   <media:title>First Video</media:title>
   <media:thumbnail url="https://i.ytimg.com/vi/abc123DEF45/hqdefault.jpg" width="480" height="360"/>
   <media:description>a description</media:description>
  </media:group>
 </entry>
 <entry>
  <id>yt:video:zzz999ZZZ99</id>
  <yt:videoId>zzz999ZZZ99</yt:videoId>
  <yt:channelId>UC_x5XG1OV2P6uZZ5FSM9Ttw</yt:channelId>
  <title>Second Video</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=zzz999ZZZ99"/>
  <author>
   <name>Example Channel</name>
   <uri>https://www.youtube.com/channel/UC_x5XG1OV2P6uZZ5FSM9Ttw</uri>
  </author>
  <published>2024-02-01T12:30:00+00:00</published>
  <updated>2024-02-01T13:00:00+00:00</updated>
  <media:group>
   <media:title>Second Video</media:title>
   <media:thumbnail url="https://i.ytimg.com/vi/zzz999ZZZ99/hqdefault.jpg" width="480" height="360"/>
   <media:description>another description</media:description>
  </media:group>
 </entry>
</feed>
"""


def test_parses_entries_in_feed_order():
    entries = parse_uploads_feed(SAMPLE_FEED)
    assert [e.video_id for e in entries] == ["abc123DEF45", "zzz999ZZZ99"]


def test_extracts_title_published_and_thumbnail():
    entries = parse_uploads_feed(SAMPLE_FEED)
    first = entries[0]
    assert first.title == "First Video"
    assert first.published_at.year == 2024
    assert first.published_at.month == 1
    assert first.published_at.day == 15
    assert first.thumbnail_url == "https://i.ytimg.com/vi/abc123DEF45/hqdefault.jpg"


def test_empty_feed_returns_no_entries():
    empty_feed = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
 <title>Empty Channel</title>
</feed>
"""
    assert parse_uploads_feed(empty_feed) == []
