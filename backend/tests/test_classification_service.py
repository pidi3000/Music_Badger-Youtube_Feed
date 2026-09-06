from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.encryption import encrypt
from app.models import ApiKey, Channel, ClassificationQueue, Upload
from app.services import classification_service, key_pool, youtube_client


async def make_channel(db_session, youtube_channel_id: str = "UCabc123") -> Channel:
    channel = Channel(youtube_channel_id=youtube_channel_id, title="Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()
    return channel


async def make_queued_upload(
    db_session, channel_id: int, video_id: str, published_at: datetime, next_check_at: datetime | None = None
) -> Upload:
    upload = Upload(
        channel_id=channel_id,
        youtube_video_id=video_id,
        title=f"title-{video_id}",
        published_at=published_at,
        thumbnail_url=None,
        fetched_via="api",
        video_type="unknown",
    )
    db_session.add(upload)
    await db_session.flush()
    db_session.add(ClassificationQueue(upload_id=upload.id, published_at=published_at, next_check_at=next_check_at))
    await db_session.flush()
    return upload


@pytest.mark.asyncio
async def test_run_worker_tick_with_empty_queue_returns_zero(db_session):
    processed = await classification_service.run_worker_tick(db_session, http_client=None)
    assert processed == 0


@pytest.mark.asyncio
async def test_classifies_newest_published_upload_first(db_session, monkeypatch):
    """When more is due than fits in one batch, the newest published_at
    uploads must be classified first — so the Feed's most recent uploads
    get a real type as fast as possible."""
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    now = datetime.utcnow()
    await make_queued_upload(db_session, channel.id, "old", now - timedelta(days=1))
    await make_queued_upload(db_session, channel.id, "new", now)
    await db_session.commit()

    captured_ids: list[str] = []

    async def fake_classify_video_types(client, api_key, video_ids, strict_shorts=False):
        captured_ids.extend(video_ids)
        return {vid: youtube_client.VideoClassification("video") for vid in video_ids}

    monkeypatch.setattr(youtube_client, "classify_video_types", fake_classify_video_types)

    processed = await classification_service.run_worker_tick(db_session, http_client=None, batch_size=1)

    assert processed == 1
    assert captured_ids == ["new"]


@pytest.mark.asyncio
async def test_terminal_classification_deletes_the_queue_row(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    upload = await make_queued_upload(db_session, channel.id, "vid1", datetime.utcnow())
    await db_session.commit()

    async def fake_classify_video_types(client, api_key, video_ids, strict_shorts=False):
        return {"vid1": youtube_client.VideoClassification("short", verified=True, duration_seconds=30)}

    monkeypatch.setattr(youtube_client, "classify_video_types", fake_classify_video_types)

    processed = await classification_service.run_worker_tick(db_session, http_client=None)

    assert processed == 1
    await db_session.refresh(upload)
    assert upload.video_type == "short"
    assert upload.video_type_verified is True
    assert upload.duration_seconds == 30

    remaining = await db_session.execute(select(ClassificationQueue).where(ClassificationQueue.upload_id == upload.id))
    assert remaining.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_live_classification_keeps_the_row_and_schedules_a_recheck(db_session, monkeypatch):
    from app.services.settings_service import get_or_create_settings

    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    upload = await make_queued_upload(db_session, channel.id, "vid1", datetime.utcnow())
    settings = await get_or_create_settings(db_session)
    settings.live_recheck_interval_minutes = 7
    await db_session.commit()

    async def fake_classify_video_types(client, api_key, video_ids, strict_shorts=False):
        return {"vid1": youtube_client.VideoClassification("live", live_status="live")}

    monkeypatch.setattr(youtube_client, "classify_video_types", fake_classify_video_types)

    before = datetime.utcnow()
    processed = await classification_service.run_worker_tick(db_session, http_client=None)
    assert processed == 1

    await db_session.refresh(upload)
    assert upload.video_type == "live"
    assert upload.live_status == "live"

    result = await db_session.execute(select(ClassificationQueue).where(ClassificationQueue.upload_id == upload.id))
    row = result.scalar_one()
    assert row.next_check_at is not None
    assert row.next_check_at >= before + timedelta(minutes=7) - timedelta(seconds=5)


@pytest.mark.asyncio
async def test_upcoming_classification_also_schedules_a_recheck(db_session, monkeypatch):
    """"Live" and "upcoming" share the single configured recheck interval
    (AppSettings.live_recheck_interval_minutes) — there's no separate,
    longer interval for upcoming streams anymore."""
    from app.services.settings_service import get_or_create_settings

    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    upload = await make_queued_upload(db_session, channel.id, "vid1", datetime.utcnow())
    settings = await get_or_create_settings(db_session)
    settings.live_recheck_interval_minutes = 7
    await db_session.commit()

    async def fake_classify_video_types(client, api_key, video_ids, strict_shorts=False):
        return {"vid1": youtube_client.VideoClassification("live", live_status="upcoming")}

    monkeypatch.setattr(youtube_client, "classify_video_types", fake_classify_video_types)

    before = datetime.utcnow()
    await classification_service.run_worker_tick(db_session, http_client=None)

    result = await db_session.execute(select(ClassificationQueue).where(ClassificationQueue.upload_id == upload.id))
    row = result.scalar_one()
    assert row.next_check_at >= before + timedelta(minutes=7) - timedelta(seconds=5)


@pytest.mark.asyncio
async def test_a_row_not_yet_due_is_skipped(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    await make_queued_upload(
        db_session, channel.id, "vid1", datetime.utcnow(), next_check_at=datetime.utcnow() + timedelta(minutes=5)
    )
    await db_session.commit()

    async def fail_if_called(client, api_key, video_ids, strict_shorts=False):
        raise AssertionError("must not classify a row that isn't due yet")

    monkeypatch.setattr(youtube_client, "classify_video_types", fail_if_called)

    processed = await classification_service.run_worker_tick(db_session, http_client=None)
    assert processed == 0


@pytest.mark.asyncio
async def test_queue_row_for_a_deleted_upload_is_cleaned_up_without_an_api_call(db_session, monkeypatch):
    channel = await make_channel(db_session)
    upload = await make_queued_upload(db_session, channel.id, "vid1", datetime.utcnow())
    await db_session.commit()
    upload_id = upload.id
    await db_session.delete(upload)
    await db_session.commit()

    async def fail_if_called(client, api_key, video_ids, strict_shorts=False):
        raise AssertionError("must not call the API for an upload that no longer exists")

    monkeypatch.setattr(youtube_client, "classify_video_types", fail_if_called)

    processed = await classification_service.run_worker_tick(db_session, http_client=None)

    assert processed == 0
    remaining = await db_session.execute(select(ClassificationQueue).where(ClassificationQueue.upload_id == upload_id))
    assert remaining.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_video_missing_from_the_response_deletes_the_row_and_leaves_upload_unknown(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    upload = await make_queued_upload(db_session, channel.id, "deleted-vid", datetime.utcnow())
    await db_session.commit()

    async def fake_classify_video_types(client, api_key, video_ids, strict_shorts=False):
        return {}  # deleted/private video, nothing came back

    monkeypatch.setattr(youtube_client, "classify_video_types", fake_classify_video_types)

    processed = await classification_service.run_worker_tick(db_session, http_client=None)

    assert processed == 1
    await db_session.refresh(upload)
    assert upload.video_type == "unknown"

    remaining = await db_session.execute(select(ClassificationQueue).where(ClassificationQueue.upload_id == upload.id))
    assert remaining.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_quota_exhausted_leaves_the_queue_intact(db_session):
    channel = await make_channel(db_session)
    # No ApiKey at all -> immediately quota-exhausted.
    upload = await make_queued_upload(db_session, channel.id, "vid1", datetime.utcnow())
    await db_session.commit()

    processed = await classification_service.run_worker_tick(db_session, http_client=None)

    assert processed == 0
    await db_session.refresh(upload)
    assert upload.video_type == "unknown"
    remaining = await db_session.execute(select(ClassificationQueue).where(ClassificationQueue.upload_id == upload.id))
    assert remaining.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_passes_the_persisted_strict_shorts_setting(db_session, monkeypatch):
    from app.services.settings_service import get_or_create_settings

    settings = await get_or_create_settings(db_session)
    settings.strict_shorts_detection = True
    db_session.add(ApiKey(label="k1", key_value_encrypted=encrypt("x")))
    channel = await make_channel(db_session)
    await make_queued_upload(db_session, channel.id, "vid1", datetime.utcnow())
    await db_session.commit()

    captured = {}

    async def fake_classify_video_types(client, api_key, video_ids, strict_shorts=False):
        captured["strict_shorts"] = strict_shorts
        return {"vid1": youtube_client.VideoClassification("video")}

    monkeypatch.setattr(youtube_client, "classify_video_types", fake_classify_video_types)

    await classification_service.run_worker_tick(db_session, http_client=None)

    assert captured["strict_shorts"] is True


def test_next_check_at_for_terminal_states_is_none():
    assert classification_service.next_check_at_for(None, 5) is None
    assert classification_service.next_check_at_for("ended", 5) is None


def test_next_check_at_for_live_and_upcoming_share_the_same_interval():
    now = datetime(2026, 1, 1, 12, 0, 0)
    assert classification_service.next_check_at_for("live", 7, now) == now + timedelta(minutes=7)
    assert classification_service.next_check_at_for("upcoming", 7, now) == now + timedelta(minutes=7)
