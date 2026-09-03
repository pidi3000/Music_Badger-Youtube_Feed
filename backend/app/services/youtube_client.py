"""Thin async wrapper over the YouTube Data API v3 REST endpoints, called
directly via httpx (no google-api-python-client — keeps everything async
and easy to mock in tests). Every call takes either an `api_key` or an
`access_token` (OAuth bearer, only for the authenticated user's own data
like `subscriptions.list`) — never both.
"""

import re
from dataclasses import dataclass, field, replace

from datetime import datetime

import httpx

from app.services.key_pool import YoutubeQuotaExceeded

API_BASE = "https://www.googleapis.com/youtube/v3"


class YoutubeApiError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"YouTube API error {status_code}: {message}")
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class ChannelInfo:
    id: str
    title: str
    thumbnail_url: str | None
    uploads_playlist_id: str | None = None
    handle: str | None = None


@dataclass(frozen=True)
class PlaylistItem:
    video_id: str
    title: str
    published_at: datetime
    thumbnail_url: str | None
    # "video" | "short" | "live" — filled in by list_uploads via a batched
    # videos.list lookup; defaults to "video" if that lookup is skipped or
    # doesn't cover this id (e.g. a deleted/private video).
    video_type: str = "video"


@dataclass(frozen=True)
class SubscriptionEntry:
    channel_id: str
    title: str
    thumbnail_url: str | None
    subscribed_at: datetime | None = None


@dataclass(frozen=True)
class Page:
    items: list
    next_page_token: str | None = None


async def _get(
    client: httpx.AsyncClient,
    path: str,
    params: dict,
    *,
    api_key: str | None = None,
    access_token: str | None = None,
) -> dict:
    request_params = dict(params)
    headers = {}
    if api_key:
        request_params["key"] = api_key
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    response = await client.get(f"{API_BASE}/{path}", params=request_params, headers=headers)

    if response.status_code == 403:
        try:
            reason = response.json()["error"]["errors"][0]["reason"]
        except (KeyError, IndexError, ValueError):
            reason = ""
        if reason in {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
            raise YoutubeQuotaExceeded(reason)

    if response.status_code >= 400:
        raise YoutubeApiError(response.status_code, response.text)

    return response.json()


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def uploads_playlist_id_for_channel(youtube_channel_id: str) -> str:
    """YouTube convention: a channel's "uploads" playlist ID is its channel
    ID with the "UC" prefix swapped for "UU" — avoids an extra
    `channels.list` call just to look up the playlist ID."""
    if youtube_channel_id.startswith("UC"):
        return "UU" + youtube_channel_id[2:]
    return youtube_channel_id


def _thumbnail_url(snippet: dict) -> str | None:
    thumbnails = snippet.get("thumbnails", {})
    for size in ("high", "medium", "default"):
        if size in thumbnails:
            return thumbnails[size]["url"]
    return None


_ISO8601_DURATION_RE = re.compile(
    r"^P(?:\d+D)?T?(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)

# YouTube's original Shorts length limit. Duration alone is a heuristic
# (Shorts also require a vertical/square aspect ratio, which isn't cheap to
# check), but it's the only signal available without extra quota cost.
_SHORT_MAX_SECONDS = 60


def _parse_duration_seconds(duration: str) -> int:
    match = _ISO8601_DURATION_RE.match(duration)
    if not match:
        return 0
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return hours * 3600 + minutes * 60 + seconds


async def _classify_video_types(
    client: httpx.AsyncClient, api_key: str, video_ids: list[str]
) -> dict[str, str]:
    """Best-effort video/short/live classification via one batched
    videos.list call — `id` accepts up to 50 comma-separated ids for a
    single quota unit, regardless of how many parts are requested.
    playlistItems (and RSS) alone don't expose duration or live status."""

    if not video_ids:
        return {}

    data = await _get(
        client,
        "videos",
        {"part": "snippet,contentDetails,liveStreamingDetails", "id": ",".join(video_ids)},
        api_key=api_key,
    )

    types: dict[str, str] = {}
    for item in data.get("items", []):
        video_id = item.get("id")
        if not video_id:
            continue
        snippet = item.get("snippet", {})
        if snippet.get("liveBroadcastContent") in ("live", "upcoming") or "liveStreamingDetails" in item:
            types[video_id] = "live"
            continue
        duration = item.get("contentDetails", {}).get("duration")
        seconds = _parse_duration_seconds(duration) if duration else 0
        types[video_id] = "short" if 0 < seconds <= _SHORT_MAX_SECONDS else "video"
    return types


async def get_channel(client: httpx.AsyncClient, api_key: str, channel_id: str) -> ChannelInfo | None:
    data = await _get(
        client,
        "channels",
        {"part": "snippet,contentDetails", "id": channel_id},
        api_key=api_key,
    )
    items = data.get("items", [])
    if not items:
        return None
    item = items[0]
    return ChannelInfo(
        id=item["id"],
        title=item["snippet"]["title"],
        thumbnail_url=_thumbnail_url(item["snippet"]),
        uploads_playlist_id=item["contentDetails"]["relatedPlaylists"]["uploads"],
    )


async def resolve_channel_by_handle(
    client: httpx.AsyncClient, api_key: str, handle: str
) -> ChannelInfo | None:
    data = await _get(
        client,
        "channels",
        {"part": "snippet,contentDetails", "forHandle": handle},
        api_key=api_key,
    )
    items = data.get("items", [])
    if not items:
        return None
    item = items[0]
    return ChannelInfo(
        id=item["id"],
        title=item["snippet"]["title"],
        thumbnail_url=_thumbnail_url(item["snippet"]),
        uploads_playlist_id=item["contentDetails"]["relatedPlaylists"]["uploads"],
        handle=handle,
    )


async def resolve_channel_id_by_video(client: httpx.AsyncClient, api_key: str, video_id: str) -> str | None:
    data = await _get(client, "videos", {"part": "snippet", "id": video_id}, api_key=api_key)
    items = data.get("items", [])
    if not items:
        return None
    return items[0]["snippet"]["channelId"]


async def list_uploads(
    client: httpx.AsyncClient,
    api_key: str,
    uploads_playlist_id: str,
    page_token: str | None = None,
    max_results: int = 50,
) -> Page:
    params = {"part": "snippet,contentDetails", "playlistId": uploads_playlist_id, "maxResults": max_results}
    if page_token:
        params["pageToken"] = page_token
    data = await _get(client, "playlistItems", params, api_key=api_key)

    items = [
        PlaylistItem(
            video_id=item["contentDetails"]["videoId"],
            title=item["snippet"]["title"],
            published_at=_parse_iso(
                item["contentDetails"].get("videoPublishedAt") or item["snippet"]["publishedAt"]
            ),
            thumbnail_url=_thumbnail_url(item["snippet"]),
        )
        for item in data.get("items", [])
    ]

    # Best-effort: a failure classifying types must not lose the uploads
    # themselves. A genuine quota exhaustion (YoutubeQuotaExceeded) is left
    # to propagate as usual so key rotation still reacts to it.
    try:
        types = await _classify_video_types(client, api_key, [item.video_id for item in items])
    except YoutubeApiError:
        types = {}
    if types:
        items = [replace(item, video_type=types.get(item.video_id, "video")) for item in items]

    return Page(items=items, next_page_token=data.get("nextPageToken"))


async def get_my_channel(client: httpx.AsyncClient, access_token: str) -> ChannelInfo | None:
    data = await _get(
        client, "channels", {"part": "snippet,contentDetails", "mine": "true"}, access_token=access_token
    )
    items = data.get("items", [])
    if not items:
        return None
    item = items[0]
    return ChannelInfo(
        id=item["id"],
        title=item["snippet"]["title"],
        thumbnail_url=_thumbnail_url(item["snippet"]),
        uploads_playlist_id=item["contentDetails"]["relatedPlaylists"]["uploads"],
    )


async def list_my_subscriptions(
    client: httpx.AsyncClient, access_token: str, page_token: str | None = None
) -> Page:
    params = {"part": "snippet", "mine": "true", "maxResults": 50}
    if page_token:
        params["pageToken"] = page_token
    data = await _get(client, "subscriptions", params, access_token=access_token)

    items = [
        SubscriptionEntry(
            channel_id=item["snippet"]["resourceId"]["channelId"],
            title=item["snippet"]["title"],
            thumbnail_url=_thumbnail_url(item["snippet"]),
            subscribed_at=(
                _parse_iso(item["snippet"]["publishedAt"]) if item["snippet"].get("publishedAt") else None
            ),
        )
        for item in data.get("items", [])
    ]
    return Page(items=items, next_page_token=data.get("nextPageToken"))
