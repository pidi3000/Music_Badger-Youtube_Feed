from datetime import datetime

import pytest
from sqlalchemy import select

from app.encryption import encrypt
from app.models import BackfillTask, Channel, SyncLog, Upload, UpdateTask
from app.services import avatar_store, oauth, rss, sync_service, youtube_client
from app.services.settings_service import get_or_create_settings


async def fake_refresh_access_token(client, config, refresh_token):
    return oauth.TokenResponse(access_token="fake-access-token", expires_in=3600)


@pytest.mark.asyncio
async def test_import_subscriptions_adds_new_and_marks_unsubscribed(db_session, monkeypatch):
    settings = await get_or_create_settings(db_session)
    settings.youtube_refresh_token_encrypted = encrypt("fake-refresh-token")
    await db_session.commit()

    chan_a = Channel(youtube_channel_id="UCaaa", title="A", source="subscription", subscription_status="subscribed")
    chan_b = Channel(youtube_channel_id="UCbbb", title="B", source="manual", subscription_status="subscribed")
    chan_c = Channel(youtube_channel_id="UCccc", title="C", source="subscription", subscription_status="subscribed")
    db_session.add_all([chan_a, chan_b, chan_c])
    await db_session.commit()

    monkeypatch.setattr(oauth, "refresh_access_token", fake_refresh_access_token)

    async def fake_list_my_subscriptions(client, access_token, page_token=None):
        return youtube_client.Page(
            items=[
                youtube_client.SubscriptionEntry(channel_id="UCaaa", title="A", thumbnail_url=None),
                youtube_client.SubscriptionEntry(channel_id="UCddd", title="D", thumbnail_url=None),
            ],
            next_page_token=None,
        )

    monkeypatch.setattr(youtube_client, "list_my_subscriptions", fake_list_my_subscriptions)

    async def fake_fetch_uploads_feed(client, youtube_channel_id):
        return []

    monkeypatch.setattr(rss, "fetch_uploads_feed", fake_fetch_uploads_feed)

    log = SyncLog(status="running")
    db_session.add(log)
    await db_session.flush()

    await sync_service.run_sync(db_session, http_client=None, log=log)

    await db_session.refresh(log)
    assert log.status == "success"
    assert log.channels_added == 1
    assert log.channels_marked_unsubscribed == 1

    result = await db_session.execute(select(Channel))
    by_id = {c.youtube_channel_id: c for c in result.scalars()}

    assert by_id["UCaaa"].subscription_status == "subscribed"
    assert by_id["UCbbb"].subscription_status == "subscribed"  # manual, untouched by unsub detection
    assert by_id["UCccc"].subscription_status == "unsubscribed"
    assert by_id["UCccc"].unsubscribed_ack is False
    assert by_id["UCccc"].unsubscribed_at is not None
    assert "UCddd" in by_id
    assert by_id["UCddd"].source == "subscription"


@pytest.mark.asyncio
async def test_import_subscriptions_commits_per_page_so_progress_is_visible_immediately(
    db_session, db_session_factory, monkeypatch
):
    settings = await get_or_create_settings(db_session)
    settings.youtube_refresh_token_encrypted = encrypt("fake-refresh-token")
    await db_session.commit()

    monkeypatch.setattr(oauth, "refresh_access_token", fake_refresh_access_token)

    pages = [
        youtube_client.Page(
            items=[youtube_client.SubscriptionEntry(channel_id="UCpage1", title="Page1 Chan", thumbnail_url=None)],
            next_page_token="page2",
        ),
        youtube_client.Page(
            items=[youtube_client.SubscriptionEntry(channel_id="UCpage2", title="Page2 Chan", thumbnail_url=None)],
            next_page_token=None,
        ),
    ]
    call_count = 0
    visible_after_page_1 = None
    status_after_page_1 = None

    async def fake_list_my_subscriptions(client, access_token, page_token=None):
        nonlocal call_count, visible_after_page_1, status_after_page_1
        if call_count == 1:
            # By the time page 2 is being fetched, page 1's channel must
            # already be committed and visible on an independent
            # connection — not just held in this session's own
            # uncommitted transaction. The log's status must still read
            # "running" at this point too — it must not have been
            # prematurely committed as "error" by a stray default that
            # gets overwritten only once the whole sync finishes (a past
            # bug: the Jobs/sync-status UI showed "error" for an import
            # that was still actively running).
            async with db_session_factory() as other_session:
                result = await other_session.execute(
                    select(Channel).where(Channel.youtube_channel_id == "UCpage1")
                )
                visible_after_page_1 = result.scalar_one_or_none() is not None
                other_log = await other_session.get(SyncLog, log.id)
                status_after_page_1 = other_log.status
        page = pages[call_count]
        call_count += 1
        return page

    monkeypatch.setattr(youtube_client, "list_my_subscriptions", fake_list_my_subscriptions)

    async def fake_fetch_uploads_feed(client, youtube_channel_id):
        return []

    monkeypatch.setattr(rss, "fetch_uploads_feed", fake_fetch_uploads_feed)

    log = SyncLog(status="running")
    db_session.add(log)
    await db_session.flush()

    await sync_service.run_sync(db_session, http_client=None, log=log)

    assert visible_after_page_1 is True
    assert status_after_page_1 == "running"
    await db_session.refresh(log)
    assert log.channels_added == 2
    assert log.status == "success"


@pytest.mark.asyncio
async def test_import_subscriptions_sets_subscribed_at_and_stores_avatar(db_session, monkeypatch):
    settings = await get_or_create_settings(db_session)
    settings.youtube_refresh_token_encrypted = encrypt("fake-refresh-token")
    await db_session.commit()

    monkeypatch.setattr(oauth, "refresh_access_token", fake_refresh_access_token)

    subscribed_at = datetime(2023, 5, 10, 8, 0, 0)

    async def fake_list_my_subscriptions(client, access_token, page_token=None):
        return youtube_client.Page(
            items=[
                youtube_client.SubscriptionEntry(
                    channel_id="UCnew1",
                    title="New Channel",
                    thumbnail_url="https://example.com/thumb.jpg",
                    subscribed_at=subscribed_at,
                ),
            ],
            next_page_token=None,
        )

    monkeypatch.setattr(youtube_client, "list_my_subscriptions", fake_list_my_subscriptions)

    async def fake_store_channel_avatar(client, youtube_channel_id, remote_url):
        assert youtube_channel_id == "UCnew1"
        assert remote_url == "https://example.com/thumb.jpg"
        return "/media/avatars/UCnew1.jpg"

    monkeypatch.setattr(avatar_store, "store_channel_avatar", fake_store_channel_avatar)

    async def fake_fetch_uploads_feed(client, youtube_channel_id):
        return []

    monkeypatch.setattr(rss, "fetch_uploads_feed", fake_fetch_uploads_feed)

    log = SyncLog(status="running")
    db_session.add(log)
    await db_session.flush()

    await sync_service.run_sync(db_session, http_client=None, log=log)

    result = await db_session.execute(select(Channel).where(Channel.youtube_channel_id == "UCnew1"))
    channel = result.scalar_one()
    assert channel.subscribed_at == subscribed_at
    assert channel.thumbnail_url == "/media/avatars/UCnew1.jpg"


@pytest.mark.asyncio
async def test_resubscribing_clears_unsubscribed_state(db_session, monkeypatch):
    settings = await get_or_create_settings(db_session)
    settings.youtube_refresh_token_encrypted = encrypt("fake-refresh-token")
    await db_session.commit()

    chan = Channel(
        youtube_channel_id="UCaaa",
        title="A",
        source="subscription",
        subscription_status="unsubscribed",
        unsubscribed_at=datetime.utcnow(),
        unsubscribed_ack=True,
    )
    db_session.add(chan)
    await db_session.commit()

    monkeypatch.setattr(oauth, "refresh_access_token", fake_refresh_access_token)

    async def fake_list_my_subscriptions(client, access_token, page_token=None):
        return youtube_client.Page(
            items=[youtube_client.SubscriptionEntry(channel_id="UCaaa", title="A", thumbnail_url=None)],
            next_page_token=None,
        )

    monkeypatch.setattr(youtube_client, "list_my_subscriptions", fake_list_my_subscriptions)

    log = SyncLog(status="running")
    db_session.add(log)
    await db_session.flush()
    await sync_service.run_sync(db_session, http_client=None, log=log)

    await db_session.refresh(chan)
    assert chan.subscription_status == "subscribed"
    assert chan.unsubscribed_at is None
    assert chan.unsubscribed_ack is False


@pytest.mark.asyncio
async def test_manual_channel_becomes_both_when_it_shows_up_as_subscription(db_session, monkeypatch):
    settings = await get_or_create_settings(db_session)
    settings.youtube_refresh_token_encrypted = encrypt("fake-refresh-token")
    await db_session.commit()

    chan = Channel(youtube_channel_id="UCaaa", title="A", source="manual", subscription_status="subscribed")
    db_session.add(chan)
    await db_session.commit()

    monkeypatch.setattr(oauth, "refresh_access_token", fake_refresh_access_token)

    async def fake_list_my_subscriptions(client, access_token, page_token=None):
        return youtube_client.Page(
            items=[youtube_client.SubscriptionEntry(channel_id="UCaaa", title="A", thumbnail_url=None)],
            next_page_token=None,
        )

    monkeypatch.setattr(youtube_client, "list_my_subscriptions", fake_list_my_subscriptions)

    log = SyncLog(status="running")
    db_session.add(log)
    await db_session.flush()
    await sync_service.run_sync(db_session, http_client=None, log=log)

    await db_session.refresh(chan)
    assert chan.source == "both"


@pytest.mark.asyncio
async def test_newly_imported_channel_gets_quick_synced_and_backfill_enqueued(db_session, monkeypatch):
    """No API key configured, so the channel's one-page "quick sync" (meant
    to make its newest uploads show up immediately) falls back to RSS —
    and a BackfillTask still gets queued for its deeper history."""

    settings = await get_or_create_settings(db_session)
    settings.youtube_refresh_token_encrypted = encrypt("fake-refresh-token")
    await db_session.commit()

    monkeypatch.setattr(oauth, "refresh_access_token", fake_refresh_access_token)

    async def fake_list_my_subscriptions(client, access_token, page_token=None):
        return youtube_client.Page(
            items=[youtube_client.SubscriptionEntry(channel_id="UCnew1", title="New Channel", thumbnail_url=None)],
            next_page_token=None,
        )

    monkeypatch.setattr(youtube_client, "list_my_subscriptions", fake_list_my_subscriptions)

    async def fake_fetch_uploads_feed(client, youtube_channel_id):
        return [rss.RssUploadEntry(video_id="rssvid1", title="RSS video", published_at=datetime.utcnow(), thumbnail_url=None)]

    monkeypatch.setattr(rss, "fetch_uploads_feed", fake_fetch_uploads_feed)

    log = SyncLog(status="running")
    db_session.add(log)
    await db_session.flush()
    await sync_service.run_sync(db_session, http_client=None, log=log)

    await db_session.refresh(log)
    assert log.rss_fallback_channels == 1

    result = await db_session.execute(select(Channel).where(Channel.youtube_channel_id == "UCnew1"))
    channel = result.scalar_one()

    uploads = list((await db_session.execute(select(Upload).where(Upload.channel_id == channel.id))).scalars())
    assert len(uploads) == 1
    assert uploads[0].fetched_via == "rss"

    backfill_tasks = list(
        (await db_session.execute(select(BackfillTask).where(BackfillTask.channel_id == channel.id))).scalars()
    )
    assert len(backfill_tasks) == 1
    assert backfill_tasks[0].status == "queued"

    # One task from the immediate quick sync (completed, via RSS) plus a
    # second, ordinary queued one from this same cycle's "every channel
    # gets an update task" pass below it — the quick sync doesn't count as
    # that cycle's task, since it already finished before that pass runs.
    update_tasks = list(
        (await db_session.execute(select(UpdateTask).where(UpdateTask.channel_id == channel.id))).scalars()
    )
    assert len(update_tasks) == 2
    quick_task = next(t for t in update_tasks if t.status == "completed")
    assert quick_task.used_rss_fallback is True
    assert any(t.status == "queued" for t in update_tasks)


@pytest.mark.asyncio
async def test_run_sync_enqueues_an_update_task_for_every_channel(db_session):
    """Every channel gets a fresh "what's new" update task enqueued each
    cycle, regardless of whether its backfill has completed — gating on
    that would leave a channel showing zero uploads for as long as its
    backfill hadn't finished."""

    chan_a = Channel(youtube_channel_id="UCaaa", title="A", source="manual", backfill_completed_at=None)
    chan_b = Channel(youtube_channel_id="UCbbb", title="B", source="manual", backfill_completed_at=datetime.utcnow())
    db_session.add_all([chan_a, chan_b])
    await db_session.commit()

    log = SyncLog(status="running")
    db_session.add(log)
    await db_session.flush()
    await sync_service.run_sync(db_session, http_client=None, log=log)

    await db_session.refresh(log)
    assert log.status == "success"

    result = await db_session.execute(select(UpdateTask))
    tasks = list(result.scalars())
    assert {t.channel_id for t in tasks} == {chan_a.id, chan_b.id}
    assert all(t.status == "queued" for t in tasks)


@pytest.mark.asyncio
async def test_run_sync_does_not_duplicate_a_still_pending_update_task(db_session):
    chan = Channel(youtube_channel_id="UCaaa", title="A", source="manual")
    db_session.add(chan)
    await db_session.flush()
    db_session.add(UpdateTask(channel_id=chan.id, status="paused_quota"))
    await db_session.commit()

    log = SyncLog(status="running")
    db_session.add(log)
    await db_session.flush()
    await sync_service.run_sync(db_session, http_client=None, log=log)

    result = await db_session.execute(select(UpdateTask).where(UpdateTask.channel_id == chan.id))
    tasks = list(result.scalars())
    assert len(tasks) == 1


@pytest.mark.asyncio
async def test_import_subscription_failure_does_not_lose_the_rest_of_the_sync(db_session, monkeypatch):
    settings = await get_or_create_settings(db_session)
    settings.youtube_refresh_token_encrypted = encrypt("fake-refresh-token")
    await db_session.commit()

    other_channel = Channel(youtube_channel_id="UCother", title="Other", source="manual")
    db_session.add(other_channel)
    await db_session.commit()

    monkeypatch.setattr(oauth, "refresh_access_token", fake_refresh_access_token)

    async def fake_list_my_subscriptions(client, access_token, page_token=None):
        raise RuntimeError("subscriptions.list unreachable")

    monkeypatch.setattr(youtube_client, "list_my_subscriptions", fake_list_my_subscriptions)

    log = SyncLog(status="running")
    db_session.add(log)
    await db_session.flush()
    await sync_service.run_sync(db_session, http_client=None, log=log)

    await db_session.refresh(log)
    assert log.status == "error"
    assert "subscriptions.list unreachable" in log.error
