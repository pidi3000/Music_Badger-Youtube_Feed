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
async def test_process_task_passes_persisted_strict_shorts_setting(db_session, monkeypatch):
    from app.services.settings_service import get_or_create_settings

    settings = await get_or_create_settings(db_session)
    settings.strict_shorts_detection = True
    await db_session.commit()

    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await backfill_service.enqueue_backfill_task(db_session, channel, fake_settings(min_count=1, days=365))
    await db_session.commit()

    captured = {}

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        captured["strict_shorts"] = strict_shorts
        return make_page([("v1", datetime.utcnow())], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await backfill_service.process_task(db_session, http_client=None, task=task)

    assert captured["strict_shorts"] is True


@pytest.mark.asyncio
async def test_completes_when_min_count_and_date_target_both_reached(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
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

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        return next(pages)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await backfill_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    await db_session.refresh(channel)
    assert task.status == "completed"
    assert task.fetched_count == 3
    assert channel.backfill_completed_at is not None


@pytest.mark.asyncio
async def test_requests_no_more_than_the_remaining_target_count(db_session, monkeypatch):
    """A target_min_count of 5 must not pull a full 50-item page on the
    first call — YouTube returns however many the request asks for, so a
    fixed maxResults=50 meant even a tiny target over-fetched relative to
    what the user configured."""

    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await backfill_service.enqueue_backfill_task(db_session, channel, fake_settings(min_count=5, days=5))
    await db_session.commit()

    now = datetime.utcnow()
    requested_max_results: list[int] = []

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        requested_max_results.append(max_results)
        # All 5 requested items are already older than the 5-day cutoff, so
        # both the count and date targets are satisfied by this one page.
        return make_page(
            [(f"v{i}", now - timedelta(days=10 + i)) for i in range(max_results)],
            next_token="more-available",
        )

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await backfill_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert requested_max_results == [5]
    assert task.status == "completed"
    assert task.fetched_count == 5


@pytest.mark.asyncio
async def test_requests_full_pages_again_once_count_target_is_met_but_date_target_is_not(db_session, monkeypatch):
    """Once target_min_count is already satisfied but target_after isn't
    (an active channel can post more than target_min_count within the
    retention window), further pages should go back to full-size requests
    — shrinking them further wouldn't reduce the total fetched, only add
    more API calls to reach the same date cutoff."""

    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await backfill_service.enqueue_backfill_task(db_session, channel, fake_settings(min_count=2, days=5))
    await db_session.commit()

    now = datetime.utcnow()
    requested_max_results: list[int] = []
    pages = iter(
        [
            # First page (sized to the target_min_count=2) is still too
            # recent to satisfy the 5-day cutoff.
            make_page([("v1", now), ("v2", now - timedelta(days=1))], next_token="p2"),
            # Count target already met; this page should be requested at
            # full size (50), not shrunk further.
            make_page([("v3", now - timedelta(days=10))], next_token=None),
        ]
    )

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        requested_max_results.append(max_results)
        return next(pages)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await backfill_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert requested_max_results == [2, 50]
    assert task.status == "completed"
    assert task.fetched_count == 3


@pytest.mark.asyncio
async def test_completes_when_channel_has_fewer_uploads_than_target(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await backfill_service.enqueue_backfill_task(db_session, channel, fake_settings(min_count=50, days=365))
    await db_session.commit()

    now = datetime.utcnow()

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        return make_page([("only-video", now)], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await backfill_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert task.status == "completed"
    assert task.fetched_count == 1


@pytest.mark.asyncio
async def test_channel_with_no_uploads_completes_immediately(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await backfill_service.enqueue_backfill_task(db_session, channel, fake_settings())
    await db_session.commit()

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        return make_page([], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await backfill_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert task.status == "completed"
    assert task.fetched_count == 0


@pytest.mark.asyncio
async def test_pauses_on_quota_exhaustion_and_resumes_from_cursor(db_session, monkeypatch):
    channel = await make_channel(db_session)
    key = ApiKey(label="k1", key_value_encrypted=encrypt("x"))
    db_session.add(key)
    await db_session.commit()

    task = await backfill_service.enqueue_backfill_task(db_session, channel, fake_settings(min_count=3, days=365))
    await db_session.commit()

    now = datetime.utcnow()
    seen_tokens: list[str | None] = []

    async def fake_list_uploads_first_page_then_quota(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
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

    async def fake_list_uploads_second_page(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
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
async def test_stop_request_between_pages_halts_before_the_next_fetch(db_session, monkeypatch):
    """A "stopping" request (see api/jobs.py's stop_job) must be honored at
    the next page boundary, not ignored until the whole backfill target is
    met — this is what makes a "Stop" button on a stuck job actually work
    rather than just marking it stopped in the UI while it keeps running."""

    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    task = await backfill_service.enqueue_backfill_task(db_session, channel, fake_settings(min_count=10, days=365))
    await db_session.commit()

    now = datetime.utcnow()
    call_count = 0

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Simulates a stop request committed by a different
            # session/request while this page's network call was in flight.
            task.status = "stopping"
            return make_page([("v1", now)], next_token="p2")
        pytest.fail("must not fetch another page once a stop was requested")

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await backfill_service.process_task(db_session, http_client=None, task=task)

    await db_session.refresh(task)
    assert task.status == "stopped"
    assert task.fetched_count == 1  # page 1's progress is kept, not discarded
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

    task = await backfill_service.enqueue_backfill_task(db_session, channel, fake_settings(min_count=1, days=365))
    await db_session.commit()

    visible_status_during_fetch = None

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        nonlocal visible_status_during_fetch
        async with db_session_factory() as other_session:
            other_task = await other_session.get(BackfillTask, task.id)
            visible_status_during_fetch = other_task.status
        return make_page([("v1", datetime.utcnow())], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await backfill_service.process_task(db_session, http_client=None, task=task)

    assert visible_status_during_fetch == "in_progress"


@pytest.mark.asyncio
async def test_worker_tick_processes_queued_and_paused_but_not_completed(db_session, monkeypatch):
    channel_a = await make_channel(db_session, "UCaaa")
    channel_b = await make_channel(db_session, "UCbbb")
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await db_session.commit()

    settings = fake_settings(min_count=1, days=365)
    await backfill_service.enqueue_backfill_task(db_session, channel_a, settings)
    await backfill_service.enqueue_backfill_task(db_session, channel_b, settings)
    await db_session.commit()

    now = datetime.utcnow()

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        return make_page([("v1", now)], next_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    processed = await backfill_service.run_worker_tick(db_session, http_client=None, max_tasks=5)

    assert processed == 2
    result = await db_session.execute(select(BackfillTask))
    statuses = {t.status for t in result.scalars()}
    assert statuses == {"completed"}
