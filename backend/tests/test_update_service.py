from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.encryption import encrypt
from app.models import ApiKey, Channel, UpdateTask
from app.services import key_pool, rss, update_service, youtube_client
from app.services.settings_service import get_or_create_settings


def make_page(pairs: list[tuple[str, datetime]], next_token: str | None = None) -> youtube_client.Page:
    items = [
        youtube_client.PlaylistItem(video_id=vid, title=f"title-{vid}", published_at=pub, thumbnail_url=None)
        for vid, pub in pairs
    ]
    return youtube_client.Page(items=items, next_page_token=next_token)


async def make_channel(db_session, youtube_channel_id: str = "UCabc123") -> Channel:
    channel = Channel(youtube_channel_id=youtube_channel_id, title="Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()
    return channel


@pytest.mark.asyncio
async def test_process_task_passes_persisted_strict_shorts_setting(db_session, monkeypatch):
    settings = await get_or_create_settings(db_session)
    settings.strict_shorts_detection = True
    await db_session.commit()

    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await update_service.enqueue_update_task(db_session, channel)
    await db_session.commit()

    captured = {}

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        captured["strict_shorts"] = strict_shorts
        return make_page([], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await update_service.process_task(db_session, http_client=None, task=task)

    assert captured["strict_shorts"] is True


@pytest.mark.asyncio
async def test_stops_paginating_once_a_page_yields_no_new_uploads(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await update_service.enqueue_update_task(db_session, channel)
    await db_session.commit()

    now = datetime.utcnow()
    pages = iter(
        [
            make_page([("v1", now)], next_token="p2"),
            make_page([], next_token="p3"),  # no new rows -> stop here, even though there's a next token
        ]
    )

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        return next(pages)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await update_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert task.status == "completed"
    assert task.fetched_count == 1
    assert task.resume_cursor is None


@pytest.mark.asyncio
async def test_stop_request_between_pages_halts_before_the_next_fetch(db_session, monkeypatch):
    """A "stopping" request (see api/jobs.py's stop_job) must be honored at
    the next page boundary rather than ignored until the task's own
    completion criteria are met."""

    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await update_service.enqueue_update_task(db_session, channel)
    await db_session.commit()

    now = datetime.utcnow()
    call_count = 0

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            task.status = "stopping"
            return make_page([("v1", now)], next_token="p2")
        pytest.fail("must not fetch another page once a stop was requested")

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await update_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert task.status == "stopped"
    assert task.fetched_count == 1
    assert call_count == 1


@pytest.mark.asyncio
async def test_in_progress_transition_is_committed_before_the_first_page_fetch(
    db_session, db_session_factory, monkeypatch
):
    """The "in_progress" transition must be committed, not just flushed,
    before the loop's first network call — a flush leaves it uncommitted,
    holding SQLite's write lock for as long as that call takes (which, with
    strict Shorts detection on, can be tens of seconds per page). A
    separate connection must see the committed row while the first page's
    fetch is still in flight, not just after process_task returns."""

    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await update_service.enqueue_update_task(db_session, channel)
    await db_session.commit()

    visible_status_during_fetch = None

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        nonlocal visible_status_during_fetch
        async with db_session_factory() as other_session:
            other_task = await other_session.get(UpdateTask, task.id)
            visible_status_during_fetch = other_task.status
        return make_page([], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await update_service.process_task(db_session, http_client=None, task=task)

    assert visible_status_during_fetch == "in_progress"


@pytest.mark.asyncio
async def test_stops_once_no_more_pages(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await update_service.enqueue_update_task(db_session, channel)
    await db_session.commit()

    now = datetime.utcnow()

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        return make_page([("v1", now)], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await update_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert task.status == "completed"
    assert task.fetched_count == 1


@pytest.mark.asyncio
async def test_stops_once_oldest_fetched_upload_crosses_the_lookback_cutoff(db_session, monkeypatch):
    settings = await get_or_create_settings(db_session)
    settings.update_lookback_days = 30
    await db_session.commit()

    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await update_service.enqueue_update_task(db_session, channel)
    await db_session.commit()

    now = datetime.utcnow()
    # Every page keeps yielding "new" uploads and has a next page, so only
    # the lookback cutoff (not "no new uploads" or "no more pages") should
    # stop this loop.
    pages = iter(
        [
            make_page([("v1", now)], next_token="p2"),
            make_page([("v2", now - timedelta(days=60))], next_token="p3"),
        ]
    )

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        return next(pages)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await update_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert task.status == "completed"
    assert task.fetched_count == 2
    assert task.resume_cursor is None


@pytest.mark.asyncio
async def test_pauses_on_quota_exhaustion_when_rss_fallback_disabled(db_session, monkeypatch):
    settings = await get_or_create_settings(db_session)
    settings.rss_fallback_enabled = False
    await db_session.commit()

    channel = await make_channel(db_session)
    key = ApiKey(label="k1", key_value_encrypted=encrypt("x"))
    db_session.add(key)
    await db_session.commit()

    task = await update_service.enqueue_update_task(db_session, channel)
    await db_session.commit()

    now = datetime.utcnow()

    async def fake_list_uploads_first_page_then_quota(
        client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False
    ):
        if page_token is None:
            return make_page([("v1", now)], next_token="p2")
        raise key_pool.YoutubeQuotaExceeded("quotaExceeded")

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads_first_page_then_quota)

    await update_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert task.status == "paused_quota"
    assert task.fetched_count == 1
    assert task.resume_cursor == "p2"


@pytest.mark.asyncio
async def test_falls_back_to_rss_on_quota_exhaustion_when_enabled(db_session, monkeypatch):
    # rss_fallback_enabled defaults to True.
    channel = await make_channel(db_session)
    await db_session.commit()  # no ApiKey at all -> immediately quota-exhausted

    task = await update_service.enqueue_update_task(db_session, channel)
    await db_session.commit()

    async def fake_fetch_uploads_feed(client, youtube_channel_id):
        return [
            rss.RssUploadEntry(video_id="rssvid1", title="RSS video", published_at=datetime.utcnow(), thumbnail_url=None)
        ]

    monkeypatch.setattr(rss, "fetch_uploads_feed", fake_fetch_uploads_feed)

    await update_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert task.status == "completed"
    assert task.used_rss_fallback is True
    assert task.fetched_count == 1

    from app.models import Upload

    result = await db_session.execute(select(Upload).where(Upload.channel_id == channel.id))
    uploads = list(result.scalars())
    assert len(uploads) == 1
    assert uploads[0].fetched_via == "rss"


@pytest.mark.asyncio
async def test_fetch_quick_sync_only_fetches_one_page_even_with_more_available(db_session, monkeypatch):
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()
    settings = await get_or_create_settings(db_session)

    now = datetime.utcnow()
    call_count = 0

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        nonlocal call_count
        call_count += 1
        return make_page([("v1", now)], next_token="p2")

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    result = await update_service.fetch_quick_sync(db_session, http_client=None, youtube_channel_id="UCabc123", settings=settings)

    assert call_count == 1
    assert result.fetched_via == "api"
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_fetch_quick_sync_does_not_touch_channel_upload_or_task_tables(db_session, monkeypatch):
    """The whole point of splitting fetch from apply is that fetching must
    be pure network I/O — no Channel/Upload/UpdateTask writes — so a caller
    can run it before creating anything, and never hold the DB write lock
    across the HTTP call."""

    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()
    settings = await get_or_create_settings(db_session)

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        return make_page([("v1", datetime.utcnow())], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await update_service.fetch_quick_sync(db_session, http_client=None, youtube_channel_id="UCabc123", settings=settings)

    assert list((await db_session.execute(select(Channel))).scalars()) == []
    assert list((await db_session.execute(select(UpdateTask))).scalars()) == []


@pytest.mark.asyncio
async def test_apply_quick_sync_persists_the_fetched_result(db_session):
    channel = await make_channel(db_session)
    await db_session.commit()

    now = datetime.utcnow()
    result = update_service.QuickSyncResult(
        items=[youtube_client.PlaylistItem(video_id="v1", title="t", published_at=now, thumbnail_url=None)],
        fetched_via="api",
    )

    task = await update_service.apply_quick_sync(db_session, channel, result)

    assert task.status == "completed"
    assert task.fetched_count == 1
    assert task.used_rss_fallback is False

    from app.models import Upload

    uploads = list((await db_session.execute(select(Upload).where(Upload.channel_id == channel.id))).scalars())
    assert len(uploads) == 1


@pytest.mark.asyncio
async def test_worker_tick_processes_queued_and_paused_but_not_completed(db_session, monkeypatch):
    channel_a = await make_channel(db_session, "UCaaa")
    channel_b = await make_channel(db_session, "UCbbb")
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    await update_service.enqueue_update_task(db_session, channel_a)
    await update_service.enqueue_update_task(db_session, channel_b)
    await db_session.commit()

    now = datetime.utcnow()

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        return make_page([("v1", now)], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    processed = await update_service.run_worker_tick(db_session, http_client=None, max_tasks=5)

    assert processed == 2
    result = await db_session.execute(select(UpdateTask))
    statuses = {t.status for t in result.scalars()}
    assert statuses == {"completed"}


@pytest.mark.asyncio
async def test_enqueue_update_task_if_needed_skips_when_one_already_pending(db_session):
    channel = await make_channel(db_session)
    await db_session.commit()

    first = await update_service.enqueue_update_task_if_needed(db_session, channel)
    await db_session.commit()
    second = await update_service.enqueue_update_task_if_needed(db_session, channel)

    assert first is not None
    assert second is None

    result = await db_session.execute(select(UpdateTask).where(UpdateTask.channel_id == channel.id))
    assert len(list(result.scalars())) == 1
