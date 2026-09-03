from datetime import datetime

import pytest
from sqlalchemy import select

from app.encryption import encrypt
from app.models import ApiKey, AppSettings, Channel, SyncLog
from app.services import avatar_store, key_pool, oauth, rss, sync_service, youtube_client
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
async def test_sync_channel_uploads_via_api_passes_strict_shorts_setting(db_session, monkeypatch):
    chan = Channel(
        youtube_channel_id="UCstrict1", title="Strict Chan", source="manual", subscription_status="subscribed"
    )
    db_session.add(chan)
    db_session.add(ApiKey(label="bg-1", group="background", key_value_encrypted=encrypt("k")))
    await db_session.commit()

    settings = AppSettings(access_secret_hash="x", upload_fetch_method="api", strict_shorts_detection=True)

    captured = {}

    async def fake_list_uploads(client, api_key, playlist_id, page_token=None, max_results=50, strict_shorts=False):
        captured["strict_shorts"] = strict_shorts
        return youtube_client.Page(items=[], next_page_token=None)

    monkeypatch.setattr(youtube_client, "list_uploads", fake_list_uploads)

    await sync_service._sync_channel_uploads_via_api(db_session, http_client=None, channel=chan, settings=settings)

    assert captured["strict_shorts"] is True


@pytest.mark.asyncio
async def test_channel_upload_sync_falls_back_to_rss_on_quota_exhaustion(db_session, monkeypatch):
    chan = Channel(
        youtube_channel_id="UCaaa",
        title="A",
        source="manual",
        subscription_status="subscribed",
        backfill_completed_at=datetime.utcnow(),
    )
    db_session.add(chan)
    await db_session.commit()

    settings = AppSettings(access_secret_hash="x", upload_fetch_method="api")

    async def raise_quota_exhausted(session, group, call):
        raise key_pool.QuotaExhaustedError(group)

    monkeypatch.setattr(key_pool, "call_with_key_rotation", raise_quota_exhausted)

    async def fake_fetch_uploads_feed(client, youtube_channel_id):
        return [rss.RssUploadEntry(video_id="rssvid1", title="RSS video", published_at=datetime.utcnow(), thumbnail_url=None)]

    monkeypatch.setattr(rss, "fetch_uploads_feed", fake_fetch_uploads_feed)

    fell_back = await sync_service._sync_channel_uploads(db_session, http_client=None, channel=chan, settings=settings)

    assert fell_back is True
    from app.models import Upload

    result = await db_session.execute(select(Upload).where(Upload.channel_id == chan.id))
    uploads = list(result.scalars())
    assert len(uploads) == 1


@pytest.mark.asyncio
async def test_channel_with_incomplete_backfill_still_gets_incremental_sync(db_session, monkeypatch):
    """Regression test: a channel whose backfill can never complete (e.g.
    only an "active"-group key configured, no "background" key — backfill
    always runs via the API, never RSS) must still receive its incremental
    "what's new" sync. Previously this was gated on
    `backfill_completed_at IS NOT NULL`, so an RSS-configured channel
    without a background key showed zero uploads forever."""

    settings = await get_or_create_settings(db_session)
    settings.upload_fetch_method = "rss"
    await db_session.commit()

    chan = Channel(
        youtube_channel_id="UCneverbackfilled",
        title="Never Backfilled",
        source="manual",
        subscription_status="subscribed",
        backfill_completed_at=None,  # backfill never finished
    )
    db_session.add(chan)
    await db_session.commit()

    async def fake_fetch_uploads_feed(client, youtube_channel_id):
        return [
            rss.RssUploadEntry(
                video_id="rssvid1", title="RSS video", published_at=datetime.utcnow(), thumbnail_url=None
            )
        ]

    monkeypatch.setattr(rss, "fetch_uploads_feed", fake_fetch_uploads_feed)

    log = SyncLog(status="running")
    db_session.add(log)
    await db_session.flush()
    await sync_service.run_sync(db_session, http_client=None, log=log)

    await db_session.refresh(log)
    assert log.status == "success"

    from app.models import Upload

    result = await db_session.execute(select(Upload).where(Upload.channel_id == chan.id))
    uploads = list(result.scalars())
    assert len(uploads) == 1
    assert uploads[0].fetched_via == "rss"


@pytest.mark.asyncio
async def test_one_channel_sync_failure_does_not_block_others_or_lose_import_counts(db_session, monkeypatch):
    settings = await get_or_create_settings(db_session)
    settings.upload_fetch_method = "rss"
    await db_session.commit()

    broken_channel = Channel(youtube_channel_id="UCbroken", title="Broken", source="manual")
    healthy_channel = Channel(youtube_channel_id="UChealthy", title="Healthy", source="manual")
    db_session.add_all([broken_channel, healthy_channel])
    await db_session.commit()

    async def fake_fetch_uploads_feed(client, youtube_channel_id):
        if youtube_channel_id == "UCbroken":
            raise RuntimeError("feed is unreachable")
        return [
            rss.RssUploadEntry(
                video_id="healthyvid1", title="ok", published_at=datetime.utcnow(), thumbnail_url=None
            )
        ]

    monkeypatch.setattr(rss, "fetch_uploads_feed", fake_fetch_uploads_feed)

    log = SyncLog(status="running")
    db_session.add(log)
    await db_session.flush()
    await sync_service.run_sync(db_session, http_client=None, log=log)

    await db_session.refresh(log)
    assert log.status == "error"
    assert log.error is not None and "UCbroken" in log.error

    from app.models import Upload

    result = await db_session.execute(select(Upload).where(Upload.channel_id == healthy_channel.id))
    uploads = list(result.scalars())
    assert len(uploads) == 1, "the healthy channel must still get synced despite the other one failing"
