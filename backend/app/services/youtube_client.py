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
    # True only when video_type was confirmed by the strict-mode redirect
    # check, not just guessed from duration — see VideoClassification.
    video_type_verified: bool = False


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
    # Total items across all pages (YouTube's `pageInfo.totalResults`), only
    # populated by list_my_subscriptions — used for the subscription import
    # progress bar, since that's the only list call where the whole result
    # set is meant to be walked page by page up front.
    total_results: int | None = None


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

# YouTube's original Shorts length limit — the default (quota-only) heuristic.
_SHORT_MAX_SECONDS = 60

# YouTube's current Shorts length cap (raised from 60s in 2024). Only a
# video at or under this length can possibly be a Short at all, so this is
# the upper bound for even attempting the strict-mode redirect check below.
_SHORTS_CANDIDATE_MAX_SECONDS = 180


def _parse_duration_seconds(duration: str) -> int:
    match = _ISO8601_DURATION_RE.match(duration)
    if not match:
        return 0
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return hours * 3600 + minutes * 60 + seconds


_SHORTS_CHECK_HEADERS = {
    # Without a browser-like User-Agent, and without pre-accepting the EU
    # cookie-consent interstitial, YouTube serves (or redirects to) a
    # consent page for *every* /shorts/{id} request regardless of whether
    # the video is actually a Short — which previously made every strict
    # check come back "not a short" (a 3xx to the consent flow, mistaken
    # for the "not a Short, redirected to /watch" signal). "CONSENT=YES+1"
    # is the long-documented way to opt out of that interstitial for an
    # unauthenticated request.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cookie": "CONSENT=YES+1",
}


async def _is_actual_short(client: httpx.AsyncClient, video_id: str) -> bool | None:
    """Unofficial (not part of the Data API, costs no quota) but well-known
    check: YouTube serves `/shorts/{id}` directly (200) for an actual Short
    and 3xx-redirects it to the normal `/watch` page otherwise — the only
    way to see the aspect-ratio signal the Data API doesn't expose for
    videos you don't own. Since it's undocumented and not guaranteed, an
    error or unexpected response returns None so the caller falls back to
    the duration heuristic instead of guessing."""

    try:
        response = await client.get(
            f"https://www.youtube.com/shorts/{video_id}",
            follow_redirects=False,
            timeout=10,
            headers=_SHORTS_CHECK_HEADERS,
        )
    except httpx.HTTPError:
        return None
    if response.status_code == 200:
        return True
    if response.status_code in (301, 302, 303, 307, 308):
        return False
    return None


@dataclass(frozen=True)
class VideoClassification:
    video_type: str
    # True only when the strict-mode redirect check (_is_actual_short) ran
    # and gave a conclusive answer — never for the duration heuristic, live
    # videos, or an inconclusive check.
    verified: bool = False


async def classify_video_types(
    client: httpx.AsyncClient, api_key: str, video_ids: list[str], strict_shorts: bool = False
) -> dict[str, VideoClassification]:
    """Best-effort video/short/live classification via one batched
    videos.list call — `id` accepts up to 50 comma-separated ids for a
    single quota unit, regardless of how many parts are requested.
    playlistItems (and RSS) alone don't expose duration or live status.

    When `strict_shorts` is on, any video that's short enough to *possibly*
    be a Short (<=180s) also gets the extra `_is_actual_short` check —
    costs no API quota, but one extra HTTP request per such video, which is
    why it's opt-in and duration-gated rather than applied to everything."""

    if not video_ids:
        return {}

    data = await _get(
        client,
        "videos",
        {"part": "snippet,contentDetails,liveStreamingDetails", "id": ",".join(video_ids)},
        api_key=api_key,
    )

    classifications: dict[str, VideoClassification] = {}
    for item in data.get("items", []):
        video_id = item.get("id")
        if not video_id:
            continue
        snippet = item.get("snippet", {})
        if snippet.get("liveBroadcastContent") in ("live", "upcoming") or "liveStreamingDetails" in item:
            classifications[video_id] = VideoClassification("live")
            continue
        duration = item.get("contentDetails", {}).get("duration")
        seconds = _parse_duration_seconds(duration) if duration else 0

        if strict_shorts and 0 < seconds <= _SHORTS_CANDIDATE_MAX_SECONDS:
            is_short = await _is_actual_short(client, video_id)
            if is_short is not None:
                classifications[video_id] = VideoClassification("short" if is_short else "video", verified=True)
                continue

        classifications[video_id] = VideoClassification("short" if 0 < seconds <= _SHORT_MAX_SECONDS else "video")
    return classifications


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
    strict_shorts: bool = False,
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
        classifications = await classify_video_types(
            client, api_key, [item.video_id for item in items], strict_shorts=strict_shorts
        )
    except YoutubeApiError:
        classifications = {}
    if classifications:
        updated_items = []
        for item in items:
            classification = classifications.get(item.video_id)
            if classification is None:
                updated_items.append(item)
            else:
                updated_items.append(
                    replace(item, video_type=classification.video_type, video_type_verified=classification.verified)
                )
        items = updated_items

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
    total_results = data.get("pageInfo", {}).get("totalResults")
    return Page(items=items, next_page_token=data.get("nextPageToken"), total_results=total_results)
