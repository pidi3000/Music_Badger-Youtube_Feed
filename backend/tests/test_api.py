import asyncio
from datetime import datetime, timedelta

import pytest

from app.encryption import encrypt
from app.models import ApiKey, BackfillTask, Channel, ChannelTag, Upload
from app.services import youtube_client


@pytest.mark.asyncio
async def test_login_requires_correct_secret(client):
    bad = await client.post("/api/auth/login", json={"secret": "wrong"})
    assert bad.status_code == 401

    good = await client.post("/api/auth/login", json={"secret": "test-secret"})
    assert good.status_code == 200
    assert "music_badger_session" in good.cookies


@pytest.mark.asyncio
async def test_auth_status_reflects_login_state(client):
    before = await client.get("/api/auth/status")
    assert before.json() == {"authenticated": False, "youtube_connected": False}

    await client.post("/api/auth/login", json={"secret": "test-secret"})

    after = await client.get("/api/auth/status")
    body = after.json()
    assert body["authenticated"] is True
    assert body["youtube_connected"] is False


@pytest.mark.asyncio
async def test_protected_endpoint_requires_auth(client):
    response = await client.get("/api/tags")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_tags_crud(authed_client):
    created = await authed_client.post("/api/tags", json={"name": "Music", "color": "#ff0000"})
    assert created.status_code == 201
    tag = created.json()
    assert tag["name"] == "Music"

    duplicate = await authed_client.post("/api/tags", json={"name": "Music", "color": "#00ff00"})
    assert duplicate.status_code == 409

    listed = await authed_client.get("/api/tags")
    assert len(listed.json()) == 1

    updated = await authed_client.patch(f"/api/tags/{tag['id']}", json={"color": "#0000ff"})
    assert updated.json()["color"] == "#0000ff"

    deleted = await authed_client.delete(f"/api/tags/{tag['id']}")
    assert deleted.status_code == 204

    listed_after = await authed_client.get("/api/tags")
    assert listed_after.json() == []


@pytest.mark.asyncio
async def test_add_channel_by_handle(authed_client, db_session, monkeypatch):
    db_session.add(ApiKey(label="active-1", key_value_encrypted=encrypt("k")))
    await db_session.commit()

    async def fake_resolve_by_handle(client, api_key, handle):
        return youtube_client.ChannelInfo(
            id="UCtestchannel1", title="Test Channel", thumbnail_url="http://x/thumb.jpg", handle=handle
        )

    monkeypatch.setattr(youtube_client, "resolve_channel_by_handle", fake_resolve_by_handle)

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        return youtube_client.Page(items=[], next_page_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    response = await authed_client.post("/api/channels", json={"channel_link": "@testchan", "tag_ids": []})
    assert response.status_code == 201
    body = response.json()
    assert body["youtube_channel_id"] == "UCtestchannel1"
    assert body["source"] == "manual"
    # The channel row is returned as soon as it's created, before quick sync
    # and backfill queueing (which happen in the background) have run.
    assert body["backfill_status"] == "not_started"

    listed = await authed_client.get("/api/channels")
    assert len(listed.json()) == 1

    await asyncio.sleep(0.1)

    channel_response = await authed_client.get(f"/api/channels/{body['id']}")
    assert channel_response.json()["backfill_status"] == "queued"


@pytest.mark.asyncio
async def test_add_channel_stores_avatar_locally_instead_of_hotlinking(authed_client, db_session, monkeypatch):
    db_session.add(ApiKey(label="active-1", key_value_encrypted=encrypt("k")))
    await db_session.commit()

    async def fake_resolve_by_handle(client, api_key, handle):
        return youtube_client.ChannelInfo(
            id="UCavatar1", title="Avatar Channel", thumbnail_url="https://example.com/remote-thumb.jpg", handle=handle
        )

    monkeypatch.setattr(youtube_client, "resolve_channel_by_handle", fake_resolve_by_handle)

    from app.services import avatar_store, channel_service

    async def fake_store_channel_avatar(client, youtube_channel_id, remote_url):
        assert youtube_channel_id == "UCavatar1"
        assert remote_url == "https://example.com/remote-thumb.jpg"
        return "/media/avatars/UCavatar1.jpg"

    monkeypatch.setattr(channel_service.avatar_store, "store_channel_avatar", fake_store_channel_avatar)

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        return youtube_client.Page(items=[], next_page_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    response = await authed_client.post("/api/channels", json={"channel_link": "@avatarchan", "tag_ids": []})
    assert response.status_code == 201
    assert response.json()["thumbnail_url"] == "/media/avatars/UCavatar1.jpg"


@pytest.mark.asyncio
async def test_add_channel_quick_syncs_newest_uploads_in_the_background(authed_client, db_session, monkeypatch):
    db_session.add(ApiKey(label="active-1", key_value_encrypted=encrypt("k")))
    await db_session.commit()

    async def fake_resolve_by_handle(client, api_key, handle):
        return youtube_client.ChannelInfo(id="UCquick1", title="Quick Channel", thumbnail_url=None, handle=handle)

    monkeypatch.setattr(youtube_client, "resolve_channel_by_handle", fake_resolve_by_handle)

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        return youtube_client.Page(
            items=[
                youtube_client.PlaylistItem(video_id="qv1", title="t", published_at=datetime.utcnow(), thumbnail_url=None)
            ],
            next_page_token=None,
        )

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    response = await authed_client.post("/api/channels", json={"channel_link": "@quickchan", "tag_ids": []})
    assert response.status_code == 201
    body = response.json()
    # Quick sync hasn't run yet — the response comes back as soon as the
    # channel row exists, not after the (background) upload fetch.
    assert body["upload_count"] == 0

    await asyncio.sleep(0.1)

    channel_response = await authed_client.get(f"/api/channels/{body['id']}")
    assert channel_response.json()["upload_count"] == 1


@pytest.mark.asyncio
async def test_add_channel_background_quick_sync_survives_a_youtube_api_error(authed_client, db_session, monkeypatch):
    """The background quick sync (see api/channels.py's
    _run_quick_sync_in_background) has nothing waiting on its result, so an
    unhandled error there (e.g. a 404 "playlist not found") would otherwise
    vanish silently — leaving the channel with no uploads and, worse, no
    backfill task ever queued. It must still enqueue the backfill task."""

    db_session.add(ApiKey(label="active-1", key_value_encrypted=encrypt("k")))
    await db_session.commit()

    async def fake_resolve_by_handle(client, api_key, handle):
        return youtube_client.ChannelInfo(id="UCbroken1", title="Broken Channel", thumbnail_url=None, handle=handle)

    monkeypatch.setattr(youtube_client, "resolve_channel_by_handle", fake_resolve_by_handle)

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        raise youtube_client.YoutubeApiError(404, "playlist not found")

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    response = await authed_client.post("/api/channels", json={"channel_link": "@brokenchan", "tag_ids": []})
    assert response.status_code == 201
    body = response.json()

    await asyncio.sleep(0.1)

    channel_response = await authed_client.get(f"/api/channels/{body['id']}")
    assert channel_response.json()["upload_count"] == 0
    assert channel_response.json()["backfill_status"] == "queued"


@pytest.mark.asyncio
async def test_add_channel_with_unparseable_link_returns_400(authed_client, db_session):
    db_session.add(ApiKey(label="active-1", key_value_encrypted=encrypt("k")))
    await db_session.commit()

    response = await authed_client.post("/api/channels", json={"channel_link": "@ab", "tag_ids": []})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_add_channel_with_no_active_keys_available_is_an_error(authed_client):
    response = await authed_client.post("/api/channels", json={"channel_link": "@somehandle", "tag_ids": []})
    assert response.status_code >= 400


@pytest.mark.asyncio
async def test_deleting_channel_cascades_to_its_uploads(authed_client, db_session):
    channel = Channel(youtube_channel_id="UCcascade1", title="Cascade Channel", source="manual")
    other_channel = Channel(youtube_channel_id="UCcascade2", title="Other Channel", source="manual")
    db_session.add_all([channel, other_channel])
    await db_session.flush()

    db_session.add_all(
        [
            Upload(
                channel_id=channel.id,
                youtube_video_id="v1",
                title="Video 1",
                published_at=datetime.utcnow(),
                thumbnail_url=None,
                fetched_via="api",
            ),
            Upload(
                channel_id=channel.id,
                youtube_video_id="v2",
                title="Video 2",
                published_at=datetime.utcnow(),
                thumbnail_url=None,
                fetched_via="api",
            ),
            Upload(
                channel_id=other_channel.id,
                youtube_video_id="v3",
                title="Other channel's video",
                published_at=datetime.utcnow(),
                thumbnail_url=None,
                fetched_via="api",
            ),
        ]
    )
    await db_session.commit()

    response = await authed_client.delete(f"/api/channels/{channel.id}")
    assert response.status_code == 204

    from sqlalchemy import select as sa_select

    remaining = await db_session.execute(sa_select(Upload))
    remaining_ids = {u.youtube_video_id for u in remaining.scalars()}
    assert remaining_ids == {"v3"}, "deleting a channel must cascade-delete its uploads, and only its uploads"


@pytest.mark.asyncio
async def test_ack_unsubscribe(authed_client, db_session):
    channel = Channel(
        youtube_channel_id="UCunsub1",
        title="Gone",
        source="subscription",
        subscription_status="unsubscribed",
        unsubscribed_at=datetime.utcnow(),
        unsubscribed_ack=False,
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)

    response = await authed_client.post(f"/api/channels/{channel.id}/ack-unsubscribe")
    assert response.status_code == 200
    assert response.json()["unsubscribed_ack"] is True


@pytest.mark.asyncio
async def test_channel_upload_stats(authed_client, db_session):
    channel = Channel(
        youtube_channel_id="UCstats1",
        title="Stats Channel",
        source="manual",
        last_synced_at=datetime(2025, 6, 1, 12, 0, 0),
    )
    other_channel = Channel(youtube_channel_id="UCstats2", title="Other Channel", source="manual")
    empty_channel = Channel(youtube_channel_id="UCstats3", title="Empty Channel", source="manual")
    db_session.add_all([channel, other_channel, empty_channel])
    await db_session.flush()

    oldest = datetime(2024, 1, 1)
    newest = datetime(2025, 1, 1)
    db_session.add_all(
        [
            Upload(
                channel_id=channel.id,
                youtube_video_id="v1",
                title="Oldest",
                published_at=oldest,
                thumbnail_url=None,
                fetched_via="api",
            ),
            Upload(
                channel_id=channel.id,
                youtube_video_id="v2",
                title="Newest",
                published_at=newest,
                thumbnail_url=None,
                fetched_via="api",
            ),
            # Belongs to a different channel — must not leak into `channel`'s stats.
            Upload(
                channel_id=other_channel.id,
                youtube_video_id="v3",
                title="Other channel's upload",
                published_at=oldest,
                thumbnail_url=None,
                fetched_via="api",
            ),
        ]
    )
    await db_session.commit()

    # Via the list endpoint (the batch/aggregate path).
    listed = await authed_client.get("/api/channels")
    by_id = {c["id"]: c for c in listed.json()}
    assert by_id[channel.id]["upload_count"] == 2
    assert by_id[channel.id]["oldest_upload_at"] == oldest.isoformat()
    assert by_id[channel.id]["last_synced_at"] == "2025-06-01T12:00:00"
    assert by_id[other_channel.id]["upload_count"] == 1

    # Via the single-channel endpoint (a separate code path).
    single = await authed_client.get(f"/api/channels/{channel.id}")
    assert single.json()["upload_count"] == 2
    assert single.json()["oldest_upload_at"] == oldest.isoformat()

    # A channel with zero uploads gets a well-defined default, not an error.
    assert by_id[empty_channel.id]["upload_count"] == 0
    assert by_id[empty_channel.id]["oldest_upload_at"] is None

    single_empty = await authed_client.get(f"/api/channels/{empty_channel.id}")
    assert single_empty.json()["upload_count"] == 0
    assert single_empty.json()["oldest_upload_at"] is None


@pytest.mark.asyncio
async def test_settings_get_and_patch(authed_client):
    initial = await authed_client.get("/api/settings")
    assert initial.status_code == 200
    body = initial.json()
    assert body["update_lookback_days"] == 30
    assert body["rss_fallback_enabled"] is True
    assert body["backfill_days"] == 365
    assert body["backfill_min_count"] == 50
    assert body["strict_shorts_detection"] is False

    updated = await authed_client.patch(
        "/api/settings", json={"update_lookback_days": 14, "rss_fallback_enabled": False, "backfill_min_count": 10}
    )
    assert updated.status_code == 200
    updated_body = updated.json()
    assert updated_body["update_lookback_days"] == 14
    assert updated_body["rss_fallback_enabled"] is False
    assert updated_body["backfill_min_count"] == 10
    assert updated_body["backfill_days"] == 365
    assert updated_body["sync_interval_minutes"] == 30
    assert updated_body["backfill_worker_interval_seconds"] == 60
    # untouched by this PATCH, which didn't include it
    assert updated_body["strict_shorts_detection"] is False


@pytest.mark.asyncio
async def test_settings_strict_shorts_detection_toggle(authed_client):
    enabled = await authed_client.patch("/api/settings", json={"strict_shorts_detection": True})
    assert enabled.json()["strict_shorts_detection"] is True

    # persisted, not just echoed back
    refetched = await authed_client.get("/api/settings")
    assert refetched.json()["strict_shorts_detection"] is True

    disabled = await authed_client.patch("/api/settings", json={"strict_shorts_detection": False})
    assert disabled.json()["strict_shorts_detection"] is False


@pytest.mark.asyncio
async def test_rescan_shorts_endpoint(authed_client, db_session, monkeypatch):
    from app.services import youtube_client

    channel = Channel(youtube_channel_id="UCrescan1", title="Rescan Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()
    db_session.add(ApiKey(label="active-1", key_value_encrypted=encrypt("k")))
    db_session.add(
        Upload(
            channel_id=channel.id,
            youtube_video_id="rescan-vid1",
            title="Recent upload",
            published_at=datetime.utcnow() - timedelta(days=1),
            thumbnail_url=None,
            fetched_via="api",
            video_type="video",
        )
    )
    await db_session.commit()

    async def fake_classify_video_types(client, api_key, video_ids, strict_shorts=False):
        assert strict_shorts is True
        return {vid: youtube_client.VideoClassification("short", verified=True) for vid in video_ids}

    monkeypatch.setattr(youtube_client, "classify_video_types", fake_classify_video_types)

    response = await authed_client.post("/api/settings/rescan-shorts")
    assert response.status_code == 200
    body = response.json()
    assert body == {"checked": 1, "reclassified": 1}


@pytest.mark.asyncio
async def test_rescan_shorts_endpoint_returns_503_with_no_active_key(authed_client, db_session):
    channel = Channel(youtube_channel_id="UCrescan2", title="Rescan Chan 2", source="manual")
    db_session.add(channel)
    await db_session.flush()
    db_session.add(
        Upload(
            channel_id=channel.id,
            youtube_video_id="rescan-vid2",
            title="Recent upload",
            published_at=datetime.utcnow() - timedelta(days=1),
            thumbnail_url=None,
            fetched_via="api",
        )
    )
    await db_session.commit()

    response = await authed_client.post("/api/settings/rescan-shorts")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_settings_interval_update_live_reschedules_the_scheduler_jobs(app, authed_client):
    from datetime import timedelta

    from app.scheduler import BACKFILL_JOB_ID, SYNC_JOB_ID

    scheduler = app.state.scheduler
    assert scheduler.get_job(SYNC_JOB_ID).trigger.interval == timedelta(minutes=30)
    assert scheduler.get_job(BACKFILL_JOB_ID).trigger.interval == timedelta(seconds=60)

    response = await authed_client.patch(
        "/api/settings",
        json={"sync_interval_minutes": 15, "backfill_worker_interval_seconds": 45},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sync_interval_minutes"] == 15
    assert body["backfill_worker_interval_seconds"] == 45

    # The running APScheduler jobs must reflect the new interval immediately
    # — not just the DB row — since that's the whole point of this feature.
    assert scheduler.get_job(SYNC_JOB_ID).trigger.interval == timedelta(minutes=15)
    assert scheduler.get_job(BACKFILL_JOB_ID).trigger.interval == timedelta(seconds=45)

    # Persisted, too — a subsequent GET reflects the change.
    refetched = await authed_client.get("/api/settings")
    assert refetched.json()["sync_interval_minutes"] == 15
    assert refetched.json()["backfill_worker_interval_seconds"] == 45


@pytest.mark.asyncio
async def test_api_keys_crud_never_exposes_raw_value(authed_client):
    created = await authed_client.post(
        "/api/api-keys", json={"label": "My Key", "key_value": "super-secret-value"}
    )
    assert created.status_code == 201
    body = created.json()
    assert "key_value" not in body
    assert "key_value_encrypted" not in body
    key_id = body["id"]

    updated = await authed_client.patch(f"/api/api-keys/{key_id}", json={"status": "disabled"})
    assert updated.json()["status"] == "disabled"

    listed = await authed_client.get("/api/api-keys")
    assert len(listed.json()) == 1

    deleted = await authed_client.delete(f"/api/api-keys/{key_id}")
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_feed_pagination_covers_all_items_without_duplicates(authed_client, db_session):
    channel = Channel(youtube_channel_id="UCfeed1", title="Feed Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()

    now = datetime.utcnow()
    for i in range(5):
        db_session.add(
            Upload(
                channel_id=channel.id,
                youtube_video_id=f"vid{i}",
                title=f"Video {i}",
                published_at=now - timedelta(days=i),
                thumbnail_url=None,
                fetched_via="api",
            )
        )
    await db_session.commit()

    seen_ids: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = await authed_client.get("/api/feed", params=params)
        assert response.status_code == 200
        page = response.json()
        seen_ids.extend(item["youtube_video_id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break

    assert seen_ids == [f"vid{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_feed_total_uploads_and_video_type_filter(authed_client, db_session):
    channel = Channel(youtube_channel_id="UCtypes1", title="Types Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()

    now = datetime.utcnow()
    db_session.add_all(
        [
            Upload(
                channel_id=channel.id,
                youtube_video_id="vid-video",
                title="A Video",
                published_at=now,
                thumbnail_url=None,
                fetched_via="api",
                video_type="video",
            ),
            Upload(
                channel_id=channel.id,
                youtube_video_id="vid-short",
                title="A Short",
                published_at=now - timedelta(hours=1),
                thumbnail_url=None,
                fetched_via="api",
                video_type="short",
                video_type_verified=True,
            ),
            Upload(
                channel_id=channel.id,
                youtube_video_id="vid-live",
                title="A Livestream",
                published_at=now - timedelta(hours=2),
                thumbnail_url=None,
                fetched_via="api",
                video_type="live",
            ),
        ]
    )
    await db_session.commit()

    all_response = await authed_client.get("/api/feed")
    all_body = all_response.json()
    assert all_body["total_uploads"] == 3
    assert len(all_body["items"]) == 3
    assert {item["video_type"] for item in all_body["items"]} == {"video", "short", "live"}
    by_video_id = {item["youtube_video_id"]: item for item in all_body["items"]}
    assert by_video_id["vid-short"]["video_type_verified"] is True
    assert by_video_id["vid-video"]["video_type_verified"] is False

    shorts_only = await authed_client.get("/api/feed", params={"video_type": "short"})
    shorts_body = shorts_only.json()
    assert [item["youtube_video_id"] for item in shorts_body["items"]] == ["vid-short"]
    # total_uploads is an app-wide count, unaffected by the filter.
    assert shorts_body["total_uploads"] == 3

    # ChannelRef now also carries enough to build a real youtube.com link.
    assert all_body["items"][0]["channel"]["youtube_channel_id"] == "UCtypes1"


@pytest.mark.asyncio
async def test_channels_untagged_filter(authed_client, db_session):
    tag_created = await authed_client.post("/api/tags", json={"name": "Music", "color": "#ff0000"})
    tag_id = tag_created.json()["id"]

    tagged = Channel(youtube_channel_id="UCtagged1", title="Tagged Chan", source="manual")
    untagged = Channel(youtube_channel_id="UCuntagged1", title="Untagged Chan", source="manual")
    db_session.add_all([tagged, untagged])
    await db_session.flush()
    db_session.add(ChannelTag(channel_id=tagged.id, tag_id=tag_id))
    await db_session.commit()

    response = await authed_client.get("/api/channels", params={"untagged": "true"})
    titles = {c["title"] for c in response.json()}
    assert titles == {"Untagged Chan"}


@pytest.mark.asyncio
async def test_channels_source_filter(authed_client, db_session):
    manual = Channel(youtube_channel_id="UCsrcmanual", title="Manual Chan", source="manual")
    subscription = Channel(youtube_channel_id="UCsrcsub", title="Sub Chan", source="subscription")
    both = Channel(youtube_channel_id="UCsrcboth", title="Both Chan", source="both")
    db_session.add_all([manual, subscription, both])
    await db_session.commit()

    manual_only = await authed_client.get("/api/channels", params={"source": "manual"})
    assert {c["title"] for c in manual_only.json()} == {"Manual Chan", "Both Chan"}

    subscription_only = await authed_client.get("/api/channels", params={"source": "subscription"})
    assert {c["title"] for c in subscription_only.json()} == {"Sub Chan", "Both Chan"}


@pytest.mark.asyncio
async def test_channels_search_by_title_is_case_insensitive_substring(authed_client, db_session):
    db_session.add_all(
        [
            Channel(youtube_channel_id="UCsearch1", title="Learn CODing Fast", source="manual"),
            Channel(youtube_channel_id="UCsearch2", title="Late Night Coding", source="manual"),
            Channel(youtube_channel_id="UCsearch3", title="Gardening Tips", source="manual"),
        ]
    )
    await db_session.commit()

    response = await authed_client.get("/api/channels", params={"search": "cod"})
    assert {c["title"] for c in response.json()} == {"Learn CODing Fast", "Late Night Coding"}

    no_match = await authed_client.get("/api/channels", params={"search": "xyz-nope"})
    assert no_match.json() == []


@pytest.mark.asyncio
async def test_channels_sort_by_upload_count_and_order(authed_client, db_session):
    few = Channel(youtube_channel_id="UCfew1", title="Few Uploads", source="manual")
    many = Channel(youtube_channel_id="UCmany1", title="Many Uploads", source="manual")
    db_session.add_all([few, many])
    await db_session.flush()

    db_session.add(
        Upload(
            channel_id=few.id,
            youtube_video_id="fv1",
            title="One",
            published_at=datetime.utcnow(),
            thumbnail_url=None,
            fetched_via="api",
        )
    )
    for i in range(3):
        db_session.add(
            Upload(
                channel_id=many.id,
                youtube_video_id=f"mv{i}",
                title=f"Many {i}",
                published_at=datetime.utcnow(),
                thumbnail_url=None,
                fetched_via="api",
            )
        )
    await db_session.commit()

    ascending = await authed_client.get("/api/channels", params={"sort": "upload_count", "order": "asc"})
    assert [c["title"] for c in ascending.json()] == ["Few Uploads", "Many Uploads"]

    descending = await authed_client.get("/api/channels", params={"sort": "upload_count", "order": "desc"})
    assert [c["title"] for c in descending.json()] == ["Many Uploads", "Few Uploads"]


@pytest.mark.asyncio
async def test_channels_subscribed_at_is_exposed(authed_client, db_session):
    subscribed_date = datetime(2022, 3, 1, 9, 0, 0)
    channel = Channel(
        youtube_channel_id="UCsubdate1",
        title="Subscribed Chan",
        source="subscription",
        subscribed_at=subscribed_date,
    )
    db_session.add(channel)
    await db_session.commit()

    response = await authed_client.get("/api/channels")
    body = response.json()[0]
    assert body["subscribed_at"] == subscribed_date.isoformat()


@pytest.mark.asyncio
async def test_backfill_tasks_list_and_retry(authed_client, db_session, monkeypatch):
    channel = Channel(youtube_channel_id="UCretry1", title="Retry Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()
    db_session.add(ApiKey(label="bg-1", key_value_encrypted=encrypt("k")))
    await db_session.flush()

    task = BackfillTask(
        channel_id=channel.id,
        status="failed",
        target_min_count=1,
        target_after=datetime.utcnow().date(),
        last_error="boom",
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    listed = await authed_client.get("/api/backfill-tasks", params={"status": "failed"})
    assert len(listed.json()) == 1

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        return youtube_client.Page(items=[], next_page_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    retried = await authed_client.post(f"/api/backfill-tasks/{task.id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_jobs_unifies_backfill_update_and_import(authed_client, db_session):
    from app.models import SyncLog, UpdateTask

    channel = Channel(youtube_channel_id="UCjobsapi1", title="Jobs API Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()

    now = datetime.utcnow()

    db_session.add(
        BackfillTask(
            channel_id=channel.id,
            status="in_progress",
            target_min_count=50,
            target_after=now.date(),
            fetched_count=10,
            started_at=now,
        )
    )
    db_session.add(
        UpdateTask(
            channel_id=channel.id,
            status="completed",
            fetched_count=3,
            used_rss_fallback=True,
            started_at=now,
            completed_at=now,
        )
    )
    db_session.add(
        SyncLog(
            status="success",
            channels_added=2,
            channels_marked_unsubscribed=1,
            started_at=now,
            finished_at=now,
        )
    )
    await db_session.commit()

    response = await authed_client.get("/api/jobs")
    assert response.status_code == 200
    body = response.json()

    kinds = {job["kind"] for job in body}
    assert kinds == {"backfill", "update", "import_subscriptions"}

    backfill_job = next(j for j in body if j["kind"] == "backfill")
    assert backfill_job["channel"]["title"] == "Jobs API Chan"
    assert backfill_job["fetched_count"] == 10
    assert backfill_job["target_min_count"] == 50
    assert backfill_job["backfill_task_id"] is not None

    update_job = next(j for j in body if j["kind"] == "update")
    assert update_job["channel"]["title"] == "Jobs API Chan"
    assert update_job["detail"] == "3 new uploads via RSS"

    import_job = next(j for j in body if j["kind"] == "import_subscriptions")
    assert import_job["channel"] is None
    assert import_job["detail"] == "2 added, 1 unsubscribed"


@pytest.mark.asyncio
async def test_jobs_kind_filter(authed_client, db_session):
    from app.models import SyncLog, UpdateTask

    channel = Channel(youtube_channel_id="UCjobsfilter1", title="Filter Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()

    now = datetime.utcnow()
    db_session.add(BackfillTask(channel_id=channel.id, status="queued", target_min_count=50, target_after=now.date()))
    db_session.add(UpdateTask(channel_id=channel.id, status="queued"))
    db_session.add(SyncLog(status="success", started_at=now, finished_at=now))
    await db_session.commit()

    response = await authed_client.get("/api/jobs", params={"kind": "update"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["kind"] == "update"


@pytest.mark.asyncio
async def test_jobs_state_filter_groups_raw_statuses(authed_client, db_session):
    from app.models import SyncLog, UpdateTask

    channel = Channel(youtube_channel_id="UCjobsstate1", title="State Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()

    now = datetime.utcnow()
    db_session.add_all(
        [
            BackfillTask(channel_id=channel.id, status="queued", target_min_count=50, target_after=now.date()),
            BackfillTask(channel_id=channel.id, status="in_progress", target_min_count=50, target_after=now.date()),
            BackfillTask(channel_id=channel.id, status="completed", target_min_count=50, target_after=now.date()),
            BackfillTask(channel_id=channel.id, status="failed", target_min_count=50, target_after=now.date()),
            UpdateTask(channel_id=channel.id, status="paused_quota"),
            SyncLog(status="running"),
            SyncLog(status="success"),
            SyncLog(status="error"),
        ]
    )
    await db_session.commit()

    async def state_kinds(state: str) -> set[str]:
        response = await authed_client.get("/api/jobs", params={"state": state})
        assert response.status_code == 200
        return {job["status"] for job in response.json()}

    assert await state_kinds("queued") == {"queued"}
    assert await state_kinds("running") == {"in_progress", "running"}
    assert await state_kinds("done") == {"completed", "success"}
    assert await state_kinds("stopped") == {"failed", "paused_quota", "error"}

    # Combined with the kind filter.
    combined = await authed_client.get("/api/jobs", params={"kind": "backfill", "state": "stopped"})
    combined_body = combined.json()
    assert len(combined_body) == 1
    assert combined_body[0]["kind"] == "backfill"
    assert combined_body[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_jobs_shows_a_running_import_with_live_progress_not_as_an_error(authed_client, db_session):
    from app.models import SyncLog

    db_session.add(
        SyncLog(
            status="running",
            channels_added=7,
            channels_marked_unsubscribed=0,
            total_subscriptions=200,
            subscriptions_processed=42,
        )
    )
    await db_session.commit()

    response = await authed_client.get("/api/jobs", params={"kind": "import_subscriptions"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "running"
    assert body[0]["detail"] == "7 channels added so far..."
    # Reuses the backfill progress bar's fields — the frontend renders a
    # progress bar off of these two whenever target_min_count is present.
    assert body[0]["fetched_count"] == 42
    assert body[0]["target_min_count"] == 200


@pytest.mark.asyncio
async def test_stop_job_marks_a_queued_backfill_task_stopped_immediately(authed_client, db_session):
    channel = Channel(youtube_channel_id="UCstop1", title="Stop Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()
    task = BackfillTask(channel_id=channel.id, status="queued", target_min_count=50, target_after=datetime.utcnow().date())
    db_session.add(task)
    await db_session.commit()

    response = await authed_client.post(f"/api/jobs/backfill-{task.id}/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "stopped"


@pytest.mark.asyncio
async def test_stop_job_marks_a_paused_backfill_task_stopped_immediately(authed_client, db_session):
    channel = Channel(youtube_channel_id="UCstop2", title="Stop Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()
    task = BackfillTask(
        channel_id=channel.id, status="paused_quota", target_min_count=50, target_after=datetime.utcnow().date()
    )
    db_session.add(task)
    await db_session.commit()

    response = await authed_client.post(f"/api/jobs/backfill-{task.id}/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "stopped"


@pytest.mark.asyncio
async def test_stop_job_only_signals_an_in_progress_backfill_task(authed_client, db_session):
    """An in-progress task can't be stopped instantly from the API — its
    own loop is what has to notice and stop itself at the next page
    boundary (see backfill_service.process_task) — so the API can only
    mark it "stopping", not "stopped" outright."""

    channel = Channel(youtube_channel_id="UCstop3", title="Stop Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()
    task = BackfillTask(
        channel_id=channel.id, status="in_progress", target_min_count=50, target_after=datetime.utcnow().date()
    )
    db_session.add(task)
    await db_session.commit()

    response = await authed_client.post(f"/api/jobs/backfill-{task.id}/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "stopping"


@pytest.mark.asyncio
async def test_stop_job_rejects_an_already_finished_backfill_task(authed_client, db_session):
    channel = Channel(youtube_channel_id="UCstop4", title="Stop Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()
    task = BackfillTask(
        channel_id=channel.id,
        status="completed",
        target_min_count=50,
        target_after=datetime.utcnow().date(),
        completed_at=datetime.utcnow(),
    )
    db_session.add(task)
    await db_session.commit()

    response = await authed_client.post(f"/api/jobs/backfill-{task.id}/stop")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_stop_job_works_for_update_tasks_and_sync_imports(authed_client, db_session):
    from app.models import SyncLog, UpdateTask

    channel = Channel(youtube_channel_id="UCstop5", title="Stop Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()
    update_task = UpdateTask(channel_id=channel.id, status="queued")
    log = SyncLog(status="running")
    db_session.add_all([update_task, log])
    await db_session.commit()

    update_response = await authed_client.post(f"/api/jobs/update-{update_task.id}/stop")
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "stopped"

    import_response = await authed_client.post(f"/api/jobs/import-{log.id}/stop")
    assert import_response.status_code == 200
    assert import_response.json()["status"] == "stopping"


@pytest.mark.asyncio
async def test_stop_job_returns_404_for_an_unknown_or_malformed_job_id(authed_client, db_session):
    missing = await authed_client.post("/api/jobs/backfill-999999/stop")
    assert missing.status_code == 404

    malformed = await authed_client.post("/api/jobs/not-a-real-kind-1/stop")
    assert malformed.status_code == 404

    no_number = await authed_client.post("/api/jobs/backfill-abc/stop")
    assert no_number.status_code == 404


@pytest.mark.asyncio
async def test_jobs_import_has_no_progress_fields_until_the_total_is_known(authed_client, db_session):
    from app.models import SyncLog

    db_session.add(SyncLog(status="running", channels_added=0, channels_marked_unsubscribed=0))
    await db_session.commit()

    response = await authed_client.get("/api/jobs", params={"kind": "import_subscriptions"})
    body = response.json()
    assert body[0]["fetched_count"] is None
    assert body[0]["target_min_count"] is None


@pytest.mark.asyncio
async def test_sync_trigger_and_status(authed_client):
    triggered = await authed_client.post("/api/sync")
    assert triggered.status_code == 202
    sync_log_id = triggered.json()["sync_log_id"]
    assert triggered.json()["status"] == "started"

    await asyncio.sleep(0.1)

    status_response = await authed_client.get("/api/sync/status")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["last_sync"] is not None
    assert body["last_sync"]["id"] == sync_log_id
    assert body["unacknowledged_unsubscribed_count"] == 0
