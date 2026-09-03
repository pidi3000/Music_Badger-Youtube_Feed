"""Public, keyless YouTube channel uploads feed
(`https://www.youtube.com/feeds/videos.xml?channel_id=...`), already
referenced in v2 (`music_feed/db_models/_channel.py`). Returns only the
~15 most recent uploads with limited metadata — see PROJECT_OUTLINE.md §6.
"""

from dataclasses import dataclass
from datetime import datetime

import feedparser
import httpx

RSS_FEED_URL = "https://www.youtube.com/feeds/videos.xml"


@dataclass(frozen=True)
class RssUploadEntry:
    video_id: str
    title: str
    published_at: datetime
    thumbnail_url: str | None
    # The public feed doesn't expose duration or live status, so RSS-sourced
    # uploads are always classified as plain "video" (best effort).
    video_type: str = "video"


def parse_uploads_feed(raw_xml: str | bytes) -> list[RssUploadEntry]:
    parsed = feedparser.parse(raw_xml)
    entries: list[RssUploadEntry] = []
    for entry in parsed.entries:
        video_id = entry.get("yt_videoid")
        if not video_id:
            continue

        published_struct = entry.get("published_parsed")
        published_at = (
            datetime(*published_struct[:6]) if published_struct else datetime.utcnow()
        )

        thumbnail_url = None
        thumbnails = entry.get("media_thumbnail")
        if thumbnails:
            thumbnail_url = thumbnails[0].get("url")

        entries.append(
            RssUploadEntry(
                video_id=video_id,
                title=entry.get("title", ""),
                published_at=published_at,
                thumbnail_url=thumbnail_url,
            )
        )
    return entries


async def fetch_uploads_feed(client: httpx.AsyncClient, youtube_channel_id: str) -> list[RssUploadEntry]:
    response = await client.get(RSS_FEED_URL, params={"channel_id": youtube_channel_id})
    response.raise_for_status()
    return parse_uploads_feed(response.text)
