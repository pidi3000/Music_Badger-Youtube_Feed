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


@pytest.fixture(autouse=True)
def _reset_shorts_check_breaker():
    """The circuit breaker for the strict-Shorts check is module-level
    state (it needs to persist across calls within one real sync/backfill
    run, not just one classify_video_types call) — reset it around every
    test so one test's inconclusive results can't trip the breaker for an
    unrelated later test."""
    youtube_client.shorts_check_breaker.reset()
    yield
    youtube_client.shorts_check_breaker.reset()

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
async def testclassify_video_types_short_via_duration():
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
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid-short"])

    assert _types_only(classifications) == {"vid-short": "short"}
    assert classifications["vid-short"].verified is False


@pytest.mark.asyncio
async def testclassify_video_types_live_via_broadcast_content():
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
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid-live"])

    assert _types_only(classifications) == {"vid-live": "live"}
    assert classifications["vid-live"].verified is False


@pytest.mark.asyncio
async def testclassify_video_types_live_via_ended_livestream_details():
    """An ended livestream reports liveBroadcastContent="none" again, but
    still carries liveStreamingDetails — must still classify as live, with
    live_status "ended" and its actual runtime as duration_seconds."""
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
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid-ended-live"])

    assert _types_only(classifications) == {"vid-ended-live": "live"}
    assert classifications["vid-ended-live"].live_status == "ended"
    assert classifications["vid-ended-live"].duration_seconds == 5400


@pytest.mark.asyncio
async def testclassify_video_types_live_status_for_currently_live_broadcast():
    response = {
        "items": [
            {
                "id": "vid-live",
                "snippet": {"liveBroadcastContent": "live"},
                "contentDetails": {"duration": "PT0S"},
                "liveStreamingDetails": {"actualStartTime": "2024-01-01T00:00:00Z"},
            }
        ]
    }
    async with _mock_client(response) as client:
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid-live"])

    assert classifications["vid-live"].video_type == "live"
    assert classifications["vid-live"].live_status == "live"


@pytest.mark.asyncio
async def testclassify_video_types_upcoming_broadcast_has_scheduled_start_at():
    response = {
        "items": [
            {
                "id": "vid-upcoming",
                "snippet": {"liveBroadcastContent": "upcoming"},
                "liveStreamingDetails": {"scheduledStartTime": "2026-09-10T18:00:00Z"},
            }
        ]
    }
    async with _mock_client(response) as client:
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid-upcoming"])

    assert classifications["vid-upcoming"].video_type == "live"
    assert classifications["vid-upcoming"].live_status == "upcoming"
    assert classifications["vid-upcoming"].scheduled_start_at == datetime(2026, 9, 10, 18, 0, 0)


@pytest.mark.asyncio
async def testclassify_video_types_normal_length_is_video():
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
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid-normal"])

    assert _types_only(classifications) == {"vid-normal": "video"}
    assert classifications["vid-normal"].duration_seconds == 605


@pytest.mark.asyncio
async def testclassify_video_types_returns_empty_for_no_ids():
    async with _mock_client({"items": []}) as client:
        classifications = await youtube_client.classify_video_types(client, "fake-key", [])

    assert classifications == {}


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
async def test_is_actual_short_none_on_redirect_to_unrelated_location():
    """A 3xx only confirms "not a Short" when it actually redirects to that
    same video's normal watch page. A redirect anywhere else — a
    consent/interstitial page, a bot-check, a region wall — is a sign the
    request itself wasn't trusted, not a statement about the video, so it
    must not be trusted as "confirmed not a Short" either (a past bug: any
    3xx at all was treated as conclusive, misclassifying real Shorts as
    normal videos whenever the request hit one of these instead of an
    actual redirect to /watch)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://consent.youtube.com/m?continue=..."}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await youtube_client._is_actual_short(client, "vid1")
    assert result is None


@pytest.mark.asyncio
async def test_is_actual_short_none_on_unexpected_status():
    client, _ = _mock_client_with_shorts_redirect({}, {"vid1": 500})
    async with client:
        result = await youtube_client._is_actual_short(client, "vid1")
    assert result is None


@pytest.mark.asyncio
async def test_is_actual_short_sends_consent_cookie_and_browser_user_agent():
    """Without these, YouTube serves/redirects to its cookie-consent
    interstitial for every request regardless of whether the video is
    actually a Short, making the whole check meaningless (a past bug: every
    video came back "not a short", even ones a duration-only check and
    manual inspection both agreed were). The consent cookie is "SOCS", not
    the older "CONSENT" cookie — YouTube retired that bypass (see
    yt-dlp/yt-dlp#7774), and CONSENT alone now redirects to
    consent.youtube.com regardless of region."""

    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await youtube_client._is_actual_short(client, "vid1")

    assert "socs=cai" in captured_headers.get("cookie", "").lower()
    assert "python-httpx" not in captured_headers.get("user-agent", "").lower()


@pytest.mark.asyncio
async def test_is_actual_short_none_on_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await youtube_client._is_actual_short(client, "vid1")
    assert result is None


@pytest.mark.asyncio
async def testclassify_video_types_strict_off_never_makes_shorts_request():
    """Default behavior: no strict_shorts flag means no extra request at
    all, regardless of duration — this must stay quota/request-free."""
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT45S"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 302})
    async with client:
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid1"])

    assert _types_only(classifications) == {"vid1": "short"}  # falls back to the duration-only heuristic
    assert classifications["vid1"].verified is False
    assert call_log == []


@pytest.mark.asyncio
async def testclassify_video_types_strict_on_confirms_duration_heuristic_and_still_records_verified():
    """A 90s video (in the candidate window, duration heuristic already
    says "video" since it's over _SHORT_MAX_SECONDS) that the redirect
    check also says isn't a Short must be recorded as verified=True even
    though the type itself didn't change — "verified" means the check ran
    and confirmed it, not just that the result was a surprise."""
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT1M30S"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 302})
    async with client:
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    assert _types_only(classifications) == {"vid1": "video"}
    assert classifications["vid1"].verified is True
    assert len(call_log) == 1


@pytest.mark.asyncio
async def test_is_actual_short_logs_the_video_duration_next_to_the_request(caplog):
    """The duration is only for the log line, right next to the request URL
    and its status — makes it easy to eyeball, from the server console,
    which checks are landing on genuinely short-enough videos."""
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT1M30S"}}
        ]
    }
    client, _ = _mock_client_with_shorts_redirect(response, {"vid1": 200})
    async with client:
        with caplog.at_level("INFO", logger="app.services.youtube_client"):
            await youtube_client.classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    matching = [r.message for r in caplog.records if r.name == "app.services.youtube_client"]
    assert len(matching) == 1
    assert "200" in matching[0]
    assert "duration: 90s" in matching[0]


@pytest.mark.asyncio
async def testclassify_video_types_strict_on_confirms_actual_short():
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT2M30S"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 200})
    async with client:
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    assert _types_only(classifications) == {"vid1": "short"}
    assert classifications["vid1"].verified is True
    assert len(call_log) == 1


@pytest.mark.asyncio
async def testclassify_video_types_strict_on_skips_request_beyond_candidate_window():
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
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    assert _types_only(classifications) == {"vid1": "video"}
    assert call_log == []


@pytest.mark.asyncio
async def testclassify_video_types_strict_on_skips_request_at_or_below_short_max():
    """A video at or under _SHORT_MAX_SECONDS is short enough that the
    duration heuristic alone is trusted — the overwhelming majority of
    uploads that short really are Shorts, so the extra request isn't
    worth making even with strict mode on."""
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT1M10S"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 200})
    async with client:
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    assert _types_only(classifications) == {"vid1": "short"}  # duration heuristic, unverified
    assert classifications["vid1"].verified is False
    assert call_log == []


@pytest.mark.asyncio
async def testclassify_video_types_strict_on_falls_back_when_check_is_inconclusive():
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT1M30S"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 500})
    async with client:
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    assert _types_only(classifications) == {"vid1": "video"}  # duration heuristic fallback (90s > _SHORT_MAX_SECONDS)
    assert classifications["vid1"].verified is False  # inconclusive check, not confirmed
    assert len(call_log) == 1


@pytest.mark.asyncio
async def testclassify_video_types_strict_on_skips_live_videos():
    """A live video must never trigger the shorts redirect check."""
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "live"}, "contentDetails": {"duration": "PT0S"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 200})
    async with client:
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    assert _types_only(classifications) == {"vid1": "live"}
    assert call_log == []


@pytest.mark.asyncio
async def testclassify_video_types_strict_on_checks_multiple_candidates_concurrently():
    """A page with several short-candidate videos must check all of them,
    not just the first — and must not serialize them one after another
    (the whole point of running them concurrently is to bound the wall
    time for a page regardless of how many candidates it has)."""
    response = {
        "items": [
            {"id": f"vid{i}", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT1M30S"}}
            for i in range(6)
        ]
    }
    statuses = {f"vid{i}": 200 if i % 2 == 0 else 302 for i in range(6)}
    client, call_log = _mock_client_with_shorts_redirect(response, statuses)
    async with client:
        classifications = await youtube_client.classify_video_types(client, "fake-key", list(statuses), strict_shorts=True)

    assert len(call_log) == 6
    for i in range(6):
        expected = "short" if i % 2 == 0 else "video"
        assert classifications[f"vid{i}"].video_type == expected
        assert classifications[f"vid{i}"].verified is True


@pytest.mark.asyncio
async def testclassify_video_types_breaker_trips_after_consecutive_inconclusive_results():
    """Repeated inconclusive checks (e.g. every request landing on a
    consent/interstitial page instead of a real answer) must eventually
    disable the strict check for a while rather than keep paying for a
    request per candidate — that's what stops one bad patch of channels
    from stalling everything downstream of it."""
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT1M30S"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 500})  # always inconclusive
    async with client:
        for _ in range(youtube_client.shorts_check_breaker.threshold):
            await youtube_client.classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)
        assert len(call_log) == youtube_client.shorts_check_breaker.threshold
        assert youtube_client.shorts_check_breaker.is_open()

        # Breaker is now open — no further request should be made at all,
        # and classification must still fall back to the duration heuristic.
        classifications = await youtube_client.classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    assert len(call_log) == youtube_client.shorts_check_breaker.threshold  # unchanged, no new request
    assert classifications["vid1"].video_type == "video"  # PT1M30S duration heuristic (90s > _SHORT_MAX_SECONDS)
    assert classifications["vid1"].verified is False


@pytest.mark.asyncio
async def testclassify_video_types_conclusive_result_resets_the_breaker():
    response = {
        "items": [
            {"id": "vid1", "snippet": {"liveBroadcastContent": "none"}, "contentDetails": {"duration": "PT1M30S"}}
        ]
    }
    client, call_log = _mock_client_with_shorts_redirect(response, {"vid1": 500})
    async with client:
        for _ in range(youtube_client.shorts_check_breaker.threshold - 1):
            await youtube_client.classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)
        assert not youtube_client.shorts_check_breaker.is_open()

        # A conclusive result in between must reset the consecutive count,
        # so one flaky patch doesn't combine with an unrelated later one.
        conclusive_client, _ = _mock_client_with_shorts_redirect(response, {"vid1": 200})
        async with conclusive_client:
            await youtube_client.classify_video_types(conclusive_client, "fake-key", ["vid1"], strict_shorts=True)

        for _ in range(youtube_client.shorts_check_breaker.threshold - 1):
            await youtube_client.classify_video_types(client, "fake-key", ["vid1"], strict_shorts=True)

    assert not youtube_client.shorts_check_breaker.is_open()


@pytest.mark.asyncio
async def test_is_actual_short_uses_head_not_get():
    """Only the status code and (on a redirect) the Location header ever
    matter here — a real Short's response is a full HTML page, so HEAD
    lets the check skip downloading it entirely."""
    captured_methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_methods.append(request.method)
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await youtube_client._is_actual_short(client, "vid1")

    assert captured_methods == ["HEAD"]
