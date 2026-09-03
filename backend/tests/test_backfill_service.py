from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.encryption import encrypt
from app.models import ApiKey, AppSettings, BackfillTask, Channel
from app.services import backfill_service, key_pool, youtube_client


def make_page(pairs: list[tuple[str, datetime]], next_token: str | None = None) -> youtube_client.Page:
    items = [
        youtube_client.PlaylistItem(video_id=vid, title=f"title-{vid}", published_at=pub, thumbnail_url=None)
        for vid, pub in pairs
    ]
    return youtube_client.Page(items=items, next_page_token=next_token)


def fake_settings(min_count: int = 3, days: int = 365) -> AppSettings:
    return AppSettings(access_secret_hash="x", backfill_min_count=min_count, backfill_days=days)


async def make_channel(db_session, youtube_channel_id: str = "UCabc123") -> Channel:
    channel = Channel(youtube_channel_id=youtube_channel_id, title="Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()
    return channel


@pytest.mark.asyncio
async def test_completes_when_min_count_and_date_target_both_reached(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", group="background", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await backfill_service.enqueue_backfill_task(db_session, channel, fake_settings(min_count=3, days=365))
    await db_session.commit()

    now = datetime.utcnow()
    pages = iter(
        [
            make_page([("v1", now), ("v2", now - timedelta(days=1))], next_token="p2"),
            make_page([("v3", now - timedelta(days=400))], next_token=None),
        ]
    )

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50):
        return next(pages)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await backfill_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    await db_session.refresh(channel)
    assert task.status == "completed"
    assert task.fetched_count == 3
    assert channel.backfill_completed_at is not None


@pytest.mark.asyncio
async def test_completes_when_channel_has_fewer_uploads_than_target(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", group="background", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await backfill_service.enqueue_backfill_task(db_session, channel, fake_settings(min_count=50, days=365))
    await db_session.commit()

    now = datetime.utcnow()

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50):
        return make_page([("only-video", now)], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await backfill_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert task.status == "completed"
    assert task.fetched_count == 1


@pytest.mark.asyncio
async def test_channel_with_no_uploads_completes_immediately(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", group="background", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await backfill_service.enqueue_backfill_task(db_session, channel, fake_settings())
    await db_session.commit()

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50):
        return make_page([], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await backfill_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert task.status == "completed"
    assert task.fetched_count == 0


@pytest.mark.asyncio
async def test_pauses_on_quota_exhaustion_and_resumes_from_cursor(db_session, monkeypatch):
    channel = await make_channel(db_session)
    key = ApiKey(label="k1", group="background", key_value_encrypted=encrypt("x"))
    db_session.add(key)
    await db_session.commit()

    task = await backfill_service.enqueue_backfill_task(db_session, channel, fake_settings(min_count=3, days=365))
    await db_session.commit()

    now = datetime.utcnow()
    seen_tokens: list[str | None] = []

    async def fake_list_uploads_first_page_then_quota(client, api_key, playlist_id, page_token=None, max_results=50):
        seen_tokens.append(page_token)
        if page_token is None:
            return make_page([("v1", now)], next_token="p2")
        raise key_pool.YoutubeQuotaExceeded("quotaExceeded")

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads_first_page_then_quota)

    await backfill_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert task.status == "paused_quota"
    assert task.fetched_count == 1
    assert task.resume_cursor == "p2"

    # simulate the quota window resetting (as get_active_key would after quota_resets_at passes)
    result = await db_session.execute(select(ApiKey).where(ApiKey.id == key.id))
    stored_key = result.scalar_one()
    stored_key.status = "active"
    stored_key.quota_resets_at = None
    await db_session.commit()

    async def fake_list_uploads_second_page(client, api_key, playlist_id, page_token=None, max_results=50):
        seen_tokens.append(page_token)
        assert page_token == "p2"
        return make_page([("v2", now - timedelta(days=400))], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads_second_page)

    await backfill_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert task.status == "completed"
    assert task.fetched_count == 2
    assert seen_tokens == [None, "p2", "p2"]


@pytest.mark.asyncio
async def test_worker_tick_processes_queued_and_paused_but_not_completed(db_session, monkeypatch):
    channel_a = await make_channel(db_session, "UCaaa")
    channel_b = await make_channel(db_session, "UCbbb")
    db_session.add(ApiKey(label="k1", group="background", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    settings = fake_settings(min_count=1, days=365)
    await backfill_service.enqueue_backfill_task(db_session, channel_a, settings)
    await backfill_service.enqueue_backfill_task(db_session, channel_b, settings)
    await db_session.commit()

    now = datetime.utcnow()

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50):
        return make_page([("v1", now)], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    processed = await backfill_service.run_worker_tick(db_session, http_client=None, max_tasks=5)

    assert processed == 2
    result = await db_session.execute(select(BackfillTask))
    statuses = {t.status for t in result.scalars()}
    assert statuses == {"completed"}
