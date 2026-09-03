import asyncio
from datetime import datetime, timedelta

import pytest

from app.encryption import encrypt
from app.models import ApiKey, BackfillTask, Channel, Upload
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
    db_session.add(ApiKey(label="active-1", group="active", key_value_encrypted=encrypt("k")))
    await db_session.commit()

    async def fake_resolve_by_handle(client, api_key, handle):
        return youtube_client.ChannelInfo(
            id="UCtestchannel1", title="Test Channel", thumbnail_url="http://x/thumb.jpg", handle=handle
        )

    monkeypatch.setattr(youtube_client, "resolve_channel_by_handle", fake_resolve_by_handle)

    response = await authed_client.post("/api/channels", json={"channel_link": "@testchan", "tag_ids": []})
    assert response.status_code == 201
    body = response.json()
    assert body["youtube_channel_id"] == "UCtestchannel1"
    assert body["source"] == "manual"
    assert body["backfill_status"] == "queued"

    listed = await authed_client.get("/api/channels")
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_channel_fetch_method_override_can_be_cleared_with_explicit_null(authed_client, db_session):
    channel = Channel(youtube_channel_id="UCoverride1", title="Override Chan", source="manual")
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)

    set_override = await authed_client.patch(
        f"/api/channels/{channel.id}", json={"upload_fetch_method": "rss"}
    )
    assert set_override.status_code == 200
    assert set_override.json()["upload_fetch_method"] == "rss"
    assert set_override.json()["effective_fetch_method"] == "rss"

    # omitting the field entirely must leave the override untouched
    unrelated_patch = await authed_client.patch(f"/api/channels/{channel.id}", json={"tag_ids": []})
    assert unrelated_patch.json()["upload_fetch_method"] == "rss"

    # an explicit null clears the override back to the global default ("api")
    cleared = await authed_client.patch(
        f"/api/channels/{channel.id}", json={"upload_fetch_method": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["upload_fetch_method"] is None
    assert cleared.json()["effective_fetch_method"] == "api"


@pytest.mark.asyncio
async def test_add_channel_with_unparseable_link_returns_400(authed_client, db_session):
    db_session.add(ApiKey(label="active-1", group="active", key_value_encrypted=encrypt("k")))
    await db_session.commit()

    response = await authed_client.post("/api/channels", json={"channel_link": "@ab", "tag_ids": []})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_add_channel_with_no_active_keys_available_is_an_error(authed_client):
    response = await authed_client.post("/api/channels", json={"channel_link": "@somehandle", "tag_ids": []})
    assert response.status_code >= 400


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
    assert body["upload_fetch_method"] == "api"
    assert body["backfill_days"] == 365
    assert body["backfill_min_count"] == 50

    updated = await authed_client.patch(
        "/api/settings", json={"upload_fetch_method": "rss", "backfill_min_count": 10}
    )
    assert updated.status_code == 200
    updated_body = updated.json()
    assert updated_body["upload_fetch_method"] == "rss"
    assert updated_body["backfill_min_count"] == 10
    assert updated_body["backfill_days"] == 365


@pytest.mark.asyncio
async def test_api_keys_crud_never_exposes_raw_value(authed_client):
    created = await authed_client.post(
        "/api/api-keys", json={"label": "My Key", "group": "background", "key_value": "super-secret-value"}
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
async def test_backfill_tasks_list_and_retry(authed_client, db_session, monkeypatch):
    channel = Channel(youtube_channel_id="UCretry1", title="Retry Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()
    db_session.add(ApiKey(label="bg-1", group="background", key_value_encrypted=encrypt("k")))
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

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50):
        return youtube_client.Page(items=[], next_page_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    retried = await authed_client.post(f"/api/backfill-tasks/{task.id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "completed"


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
