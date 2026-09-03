"""Validates response parsing (especially thumbnail_url extraction)
against realistic YouTube Data API v3 response shapes, matching Google's
documented schema. This sandbox has no outbound network access to the
real API (blocked by policy), so this is the closest available check that
the extraction logic itself is correct.
"""

from datetime import datetime

import httpx
import pytest

from app.services import youtube_client

CHANNEL_RESPONSE = {
    "kind": "youtube#channelListResponse",
    "items": [
        {
            "kind": "youtube#channel",
            "id": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
            "snippet": {
                "title": "Google for Developers",
                "description": "Some description",
                "customUrl": "@googlefordevelopers",
                "publishedAt": "2007-08-23T00:34:43Z",
                "thumbnails": {
                    "default": {
                        "url": "https://yt3.ggpht.com/example=s88-c-k-c0x00ffffff-no-rj",
                        "width": 88,
                        "height": 88,
                    },
                    "medium": {
                        "url": "https://yt3.ggpht.com/example=s240-c-k-c0x00ffffff-no-rj",
                        "width": 240,
                        "height": 240,
                    },
                    "high": {
                        "url": "https://yt3.ggpht.com/example=s800-c-k-c0x00ffffff-no-rj",
                        "width": 800,
                        "height": 800,
                    },
                },
            },
            "contentDetails": {
                "relatedPlaylists": {
                    "likes": "",
                    "uploads": "UU_x5XG1OV2P6uZZ5FSM9Ttw",
                }
            },
        }
    ],
}

VIDEO_RESPONSE = {
    "kind": "youtube#videoListResponse",
    "items": [
        {
            "kind": "youtube#video",
            "id": "dQw4w9WgXcQ",
            "snippet": {
                "publishedAt": "2009-10-25T06:57:33Z",
                "channelId": "UC_x5XG1OV2P6uZZ5FSM9Ttw",
                "title": "Some Video",
            },
        }
    ],
}

PLAYLIST_ITEMS_RESPONSE = {
    "kind": "youtube#playlistItemListResponse",
    "nextPageToken": "CAUQAA",
    "items": [
        {
            "kind": "youtube#playlistItem",
            "snippet": {
                "publishedAt": "2024-01-15T18:00:00Z",
                "title": "Upload Title",
                "thumbnails": {
                    "default": {"url": "https://i.ytimg.com/vi/abc123/default.jpg"},
                    "medium": {"url": "https://i.ytimg.com/vi/abc123/mqdefault.jpg"},
                    "high": {"url": "https://i.ytimg.com/vi/abc123/hqdefault.jpg"},
                },
            },
            "contentDetails": {
                "videoId": "abc123",
                "videoPublishedAt": "2024-01-15T18:00:00Z",
            },
        }
    ],
}

SUBSCRIPTIONS_RESPONSE = {
    "kind": "youtube#subscriptionListResponse",
    "items": [
        {
            "kind": "youtube#subscription",
            "snippet": {
                "title": "Some Channel",
                "resourceId": {"kind": "youtube#channel", "channelId": "UCsomeid12345678901234"},
                "publishedAt": "2023-05-10T08:00:00Z",
                "thumbnails": {
                    "default": {"url": "https://yt3.ggpht.com/sub-default.jpg"},
                    "medium": {"url": "https://yt3.ggpht.com/sub-medium.jpg"},
                    "high": {"url": "https://yt3.ggpht.com/sub-high.jpg"},
                },
            },
        }
    ],
}


def _mock_client(response_json: dict) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_json, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _mock_multi_client(by_path_substring: dict[str, dict]) -> httpx.AsyncClient:
    """Routes to a different canned response depending on which YouTube API
    endpoint the request hit — needed for list_uploads, which now makes a
    second (videos.list) call to classify each upload's type."""

    def handler(request: httpx.Request) -> httpx.Response:
        for substring, response_json in by_path_substring.items():
            if substring in str(request.url):
                return httpx.Response(200, json=response_json, request=request)
        return httpx.Response(200, json={"items": []}, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_get_channel_extracts_thumbnail_and_uploads_playlist():
    async with _mock_client(CHANNEL_RESPONSE) as client:
        info = await youtube_client.get_channel(client, "fake-key", "UC_x5XG1OV2P6uZZ5FSM9Ttw")

    assert info is not None
    assert info.title == "Google for Developers"
    assert info.thumbnail_url == "https://yt3.ggpht.com/example=s800-c-k-c0x00ffffff-no-rj"
    assert info.uploads_playlist_id == "UU_x5XG1OV2P6uZZ5FSM9Ttw"


@pytest.mark.asyncio
async def test_resolve_channel_by_handle_extracts_thumbnail():
    async with _mock_client(CHANNEL_RESPONSE) as client:
        info = await youtube_client.resolve_channel_by_handle(client, "fake-key", "@googlefordevelopers")

    assert info is not None
    assert info.thumbnail_url == "https://yt3.ggpht.com/example=s800-c-k-c0x00ffffff-no-rj"


@pytest.mark.asyncio
async def test_resolve_channel_id_by_video():
    async with _mock_client(VIDEO_RESPONSE) as client:
        channel_id = await youtube_client.resolve_channel_id_by_video(client, "fake-key", "dQw4w9WgXcQ")

    assert channel_id == "UC_x5XG1OV2P6uZZ5FSM9Ttw"


@pytest.mark.asyncio
async def test_list_uploads_extracts_thumbnail_and_published_date():
    async with _mock_client(PLAYLIST_ITEMS_RESPONSE) as client:
        page = await youtube_client.list_uploads(client, "fake-key", "UU_x5XG1OV2P6uZZ5FSM9Ttw")

    assert len(page.items) == 1
    item = page.items[0]
    assert item.video_id == "abc123"
    assert item.thumbnail_url == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"
    assert item.published_at.year == 2024
    assert page.next_page_token == "CAUQAA"


@pytest.mark.asyncio
async def test_list_my_subscriptions_extracts_channel_id_and_thumbnail():
    async with _mock_client(SUBSCRIPTIONS_RESPONSE) as client:
        page = await youtube_client.list_my_subscriptions(client, "fake-access-token")

    assert len(page.items) == 1
    entry = page.items[0]
    assert entry.channel_id == "UCsomeid12345678901234"
    assert entry.thumbnail_url == "https://yt3.ggpht.com/sub-high.jpg"


@pytest.mark.asyncio
async def test_get_channel_returns_none_when_channel_has_no_high_or_medium_thumbnail():
    """Edge case: only a "default" thumbnail present should still resolve,
    not silently return no thumbnail at all."""

    response = {
        "items": [
            {
                "id": "UCabc",
                "snippet": {
                    "title": "Minimal Channel",
                    "thumbnails": {"default": {"url": "https://yt3.ggpht.com/only-default.jpg"}},
                },
                "contentDetails": {"relatedPlaylists": {"uploads": "UUabc"}},
            }
        ]
    }
    async with _mock_client(response) as client:
        info = await youtube_client.get_channel(client, "fake-key", "UCabc")

    assert info is not None
    assert info.thumbnail_url == "https://yt3.ggpht.com/only-default.jpg"


@pytest.mark.asyncio
async def test_get_channel_returns_none_thumbnail_when_thumbnails_key_missing_entirely():
    response = {
        "items": [
            {
                "id": "UCabc",
                "snippet": {"title": "No Thumbnails Channel"},
                "contentDetails": {"relatedPlaylists": {"uploads": "UUabc"}},
            }
        ]
    }
    async with _mock_client(response) as client:
        info = await youtube_client.get_channel(client, "fake-key", "UCabc")

    assert info is not None
    assert info.thumbnail_url is None


@pytest.mark.asyncio
async def test_list_my_subscriptions_extracts_subscribed_at():
    async with _mock_client(SUBSCRIPTIONS_RESPONSE) as client:
        page = await youtube_client.list_my_subscriptions(client, "fake-access-token")

    assert page.items[0].subscribed_at == datetime(2023, 5, 10, 8, 0, 0)


@pytest.mark.parametrize(
    "duration, expected_seconds",
    [
        ("PT45S", 45),
        ("PT10M5S", 605),
        ("PT1H2M3S", 3723),
        ("PT0S", 0),
        ("garbage", 0),
    ],
)
def test_parse_duration_seconds(duration, expected_seconds):
    assert youtube_client._parse_duration_seconds(duration) == expected_seconds


def _types_only(classifications: dict) -> dict:
    return {video_id: c.video_type for video_id, c in classifications.items()}


@pytest.mark.asyncio
async def test_classify_video_types_short_via_duration():
    response = {
        "items": [
            {
                "id": "vid-short",
                "snippet": {"liveBroadcastContent": "none"},
                "contentDetails": {"duration": "PT45S"},
            }
        ]
    }
    async with _mock_client(response) as client:
        classifications = await youtube_client._classify_video_types(client, "fake-key", ["vid-short"])

    assert _types_only(classifications) == {"vid-short": "short"}
    assert classifications["vid-short"].verified is False


@pytest.mark.asyncio
async def test_classify_video_types_live_via_broadcast_content():
    response = {
        "items": [
            {
                "id": "vid-live",
                "snippet": {"liveBroadcastContent": "live"},
                "contentDetails": {"duration": "PT0S"},
            }
        ]
    }
    async with _mock_client(response) as client:
        classifications = await youtube_client._classify_video_types(client, "fake-key", ["vid-live"])

    assert _types_only(classifications) == {"vid-live": "live"}
    assert classifications["vid-live"].verified is False


@pytest.mark.asyncio
async def test_classify_video_types_live_via_ended_livestream_details():
    """An ended livestream reports liveBroadcastContent="none" again, but
    still carries liveStreamingDetails — must still classify as live."""
    response = {
        "items": [
            {
                "id": "vid-ended-live",
                "snippet": {"liveBroadcastContent": "none"},
                "contentDetails": {"duration": "PT1H30M"},
                "liveStreamingDetails": {"actualStartTime": "2024-01-01T00:00:00Z"},
            }
        ]
    }
    async with _mock_client(response) as client:
        classifications = await youtube_client._classify_video_types(client, "fake-key", ["vid-ended-live"])

    assert _types_only(classifications) == {"vid-ended-live": "live"}


@pytest.mark.asyncio
async def test_classify_video_types_normal_length_is_video():
    response = {
        "items": [
            {
                "id": "vid-normal",
                "snippet": {"liveBroadcastContent": "none"},
                "contentDetails": {"duration": "PT10M5S"},
            }
        ]
    }
    async with _mock_client(response) as client:
        classifications = await youtube_client._classify_video_types(client, "fake-key", ["vid-normal"])

    assert _types_only(classifications) == {"vid-normal": "video"}


@pytest.mark.asyncio
async def test_classify_video_types_returns_empty_for_no_ids():
    async with _mock_client({"items": []}) as client:
        classifications = await youtube_client._classify_video_types(client, "fake-key", [])

    assert classifications == {}


@pytest.mark.asyncio
async def test_list_uploads_fills_in_video_type_from_classification():
    async with _mock_multi_client(
        {
            "playlistItems": PLAYLIST_ITEMS_RESPONSE,
            "videos": {
                "items": [
                    {
                        "id": "abc123",
                        "snippet": {"liveBroadcastContent": "none"},
                        "contentDetails": {"duration": "PT45S"},
                    }
                ]
            },
        }
    ) as client:
        page = await youtube_client.list_uploads(client, "fake-key", "UU_x5XG1OV2P6uZZ5FSM9Ttw")

    assert page.items[0].video_type == "short"


def _mock_client_with_shorts_redirect(videos_response: dict, shorts_status_by_id: dict):
    """Routes googleapis.com calls to `videos_response`, and the unofficial
    youtube.com/shorts/{id} redirect check to a per-id status code — 200
    means "actually a Short", a 3xx means "redirected to /watch, not a
    Short". Also returns the list of shorts-check URLs actually requested,
    so tests can assert the request was (or wasn't) made at all."""

    call_log: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "youtube.com/shorts/" in url:
            call_log.append(url)
            video_id = url.rsplit("/", 1)[-1]
            status = shorts_status_by_id.get(video_id, 404)
            if status in (301, 302, 303, 307, 308):
                return httpx.Response(
                    status, headers={"location": f"https://www.youtube.com/watch?v={video_id}"}, request=request
                )
            return httpx.Response(status, request=request)
        return httpx.Response(200, json=videos_response, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), call_log


@pytest.mark.asyncio
async def test_is_actual_short_true_on_200():
    client, _ = _mock_client_with_shorts_redirect({}, {"vid1": 200})
    async with client:
        result = await youtube_client._is_actual_short(client, "vid1")
    assert result is True


@pytest.mark.asyncio
async def test_is_actual_short_false_on_redirect():
    client, _ = _mock_client_with_shorts_redirect({}, {"vid1": 302})
    async with client:
        result = await youtube_client._is_actual_short(client, "vid1")
    assert result is False


@pytest.mark.asyncio
async def test_is_actual_short_none_on_unexpected_status():
    client, _ = _mock_client_with_shorts_redirect({}, {"vid1": 500})
    async with client:
        result = await youtube_client._is_actual_short(client, "vid1")
    assert result is None


@pytest.mark.asyncio
async def test_is_actual_short_none_on_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await youtube_client._is_actual_short(client, "vid1")
    assert result is None


@pytest.mark.asyncio
async def test_classify_video_types_strict_off_never_makes_shorts_request():
    """Default behavior: no strict_shorts flag means no extra request at
    all, regardless of duration — this must stay quota/request-free."""
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT45S"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 302})
    async with client:
        classifications = await youtube_client._classify_video_types(client, "fake-key", ["vid1"])

    assert _types_only(classifications) == {"vid1": "short"}  # falls back to the duration-only heuristic
    assert classifications["vid1"].verified is False
    assert call_log == []


@pytest.mark.asyncio
async def test_classify_video_types_strict_on_overrides_duration_heuristic():
    """A 45s video that is NOT actually a Short (e.g. a widescreen clip)
    must be corrected to "video" by the redirect check when strict mode
    is on, even though duration alone would call it a short — and the
    correction must be recorded as verified."""
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT45S"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 302})
    async with client:
        classifications = await youtube_client._classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    assert _types_only(classifications) == {"vid1": "video"}
    assert classifications["vid1"].verified is True
    assert len(call_log) == 1


@pytest.mark.asyncio
async def test_classify_video_types_strict_on_confirms_actual_short():
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT2M30S"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 200})
    async with client:
        classifications = await youtube_client._classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    assert _types_only(classifications) == {"vid1": "short"}
    assert classifications["vid1"].verified is True
    assert len(call_log) == 1


@pytest.mark.asyncio
async def test_classify_video_types_strict_on_skips_request_beyond_candidate_window():
    """Duration alone already rules a >180s video out as a Short, so the
    extra request must not be made at all — that's the whole point of
    gating it on the candidate window."""
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT10M"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 200})
    async with client:
        classifications = await youtube_client._classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    assert _types_only(classifications) == {"vid1": "video"}
    assert call_log == []


@pytest.mark.asyncio
async def test_classify_video_types_strict_on_falls_back_when_check_is_inconclusive():
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT45S"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 500})
    async with client:
        classifications = await youtube_client._classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    assert _types_only(classifications) == {"vid1": "short"}  # duration heuristic fallback
    assert classifications["vid1"].verified is False  # inconclusive check, not confirmed
    assert len(call_log) == 1


@pytest.mark.asyncio
async def test_classify_video_types_strict_on_skips_live_videos():
    """A live video must never trigger the shorts redirect check."""
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "live"}, "contentDetails": {"duration": "PT0S"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 200})
    async with client:
        classifications = await youtube_client._classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    assert _types_only(classifications) == {"vid1": "live"}
    assert call_log == []


@pytest.mark.asyncio
async def test_list_uploads_strict_shorts_flag_reaches_the_redirect_check():
    videos_response = {
        "items": [
            {"id": "abc123", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT45S"}}
        ]
    }
    call_log: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "youtube.com/shorts/" in url:
            call_log.append(url)
            return httpx.Response(302, headers={"location": "https://www.youtube.com/watch?v=abc123"}, request=request)
        if "playlistItems" in url:
            return httpx.Response(200, json=PLAYLIST_ITEMS_RESPONSE, request=request)
        return httpx.Response(200, json=videos_response, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await youtube_client.list_uploads(
            client, "fake-key", "UU_x5XG1OV2P6uZZ5FSM9Ttw", strict_shorts=True
        )

    # The redirect check said "not a Short" — must override the duration
    # heuristic (45s would otherwise say "short") and record it as verified.
    assert page.items[0].video_type == "video"
    assert page.items[0].video_type_verified is True
    assert len(call_log) == 1


@pytest.mark.asyncio
async def test_list_uploads_defaults_video_type_when_classification_lookup_omits_the_id():
    """A video id missing from the videos.list response (e.g. deleted)
    must not crash the upload fetch — it just defaults to "video", unverified."""
    async with _mock_multi_client(
        {"playlistItems": PLAYLIST_ITEMS_RESPONSE, "videos": {"items": []}}
    ) as client:
        page = await youtube_client.list_uploads(client, "fake-key", "UU_x5XG1OV2P6uZZ5FSM9Ttw")

    assert page.items[0].video_type == "video"
    assert page.items[0].video_type_verified is False
