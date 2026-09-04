from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.encryption import encrypt
from app.models import ApiKey, Channel, Upload
from app.services import key_pool, reclassify_service, youtube_client


async def make_channel(db_session, youtube_channel_id: str = "UCabc123") -> Channel:
    channel = Channel(youtube_channel_id=youtube_channel_id, title="Chan", source="manual")
    db_session.add(channel)
    await db_session.flush()
    return channel


def make_upload(
    channel_id: int,
    video_id: str,
    published_at: datetime,
    video_type: str = "video",
    video_type_verified: bool = False,
    fetched_via: str = "api",
) -> Upload:
    return Upload(
        channel_id=channel_id,
        youtube_video_id=video_id,
        title=f"title-{video_id}",
        published_at=published_at,
        thumbnail_url=None,
        fetched_via=fetched_via,
        video_type=video_type,
        video_type_verified=video_type_verified,
    )


@pytest.mark.asyncio
async def test_rescan_only_touches_unverified_uploads_within_the_window(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="active-1", group="active", key_value_encrypted=encrypt("k")))

    now = datetime.utcnow()
    recent_unverified = make_upload(channel.id, "recent-unverified", now - timedelta(days=1))
    recent_verified = make_upload(channel.id, "recent-verified", now - timedelta(days=1), video_type_verified=True)
    old_unverified = make_upload(channel.id, "old-unverified", now - timedelta(days=30))
    db_session.add_all([recent_unverified, recent_verified, old_unverified])
    await db_session.commit()

    captured_ids: list[str] = []

    async def fake_classify_video_types(client, api_key, video_ids, strict_shorts=False):
        captured_ids.extend(video_ids)
        assert strict_shorts is True
        return {vid: youtube_client.VideoClassification("short", verified=True) for vid in video_ids}

    monkeypatch.setattr(youtube_client, "classify_video_types", fake_classify_video_types)

    result = await reclassify_service.rescan_recent_uploads(db_session, http_client=None)

    assert captured_ids == ["recent-unverified"]  # verified and old uploads excluded
    assert result.checked == 1
    assert result.reclassified == 1  # "video" -> "short"

    await db_session.refresh(recent_unverified)
    assert recent_unverified.video_type == "short"
    assert recent_unverified.video_type_verified is True

    await db_session.refresh(recent_verified)
    assert recent_verified.video_type == "video"  # untouched, was already verified

    await db_session.refresh(old_unverified)
    assert old_unverified.video_type == "video"  # untouched, outside the window


@pytest.mark.asyncio
async def test_rescan_with_nothing_eligible_makes_no_api_call(db_session, monkeypatch):
    channel = await make_channel(db_session)
    old_upload = make_upload(channel.id, "old1", datetime.utcnow() - timedelta(days=30))
    db_session.add(old_upload)
    await db_session.commit()

    async def fail_if_called(client, api_key, video_ids, strict_shorts=False):
        raise AssertionError("classify_video_types should not be called when nothing is eligible")

    monkeypatch.setattr(youtube_client, "classify_video_types", fail_if_called)

    result = await reclassify_service.rescan_recent_uploads(db_session, http_client=None)

    assert result.checked == 0
    assert result.reclassified == 0


@pytest.mark.asyncio
async def test_rescan_marks_verified_even_when_type_is_unchanged(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="active-1", group="active", key_value_encrypted=encrypt("k")))
    upload = make_upload(channel.id, "vid1", datetime.utcnow() - timedelta(hours=1), video_type="video")
    db_session.add(upload)
    await db_session.commit()

    async def fake_classify_video_types(client, api_key, video_ids, strict_shorts=False):
        return {"vid1": youtube_client.VideoClassification("video", verified=True)}

    monkeypatch.setattr(youtube_client, "classify_video_types", fake_classify_video_types)

    result = await reclassify_service.rescan_recent_uploads(db_session, http_client=None)

    assert result.checked == 1
    assert result.reclassified == 0  # type didn't change

    await db_session.refresh(upload)
    assert upload.video_type == "video"
    assert upload.video_type_verified is True  # still marked verified so it's not rescanned again


@pytest.mark.asyncio
async def test_rescan_leaves_ids_missing_from_the_response_untouched(db_session, monkeypatch):
    """A deleted/private video won't appear in the videos.list response —
    it must stay unverified (eligible for a future retry) rather than
    crash or get silently marked verified."""
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="active-1", group="active", key_value_encrypted=encrypt("k")))
    upload = make_upload(channel.id, "deleted-vid", datetime.utcnow() - timedelta(hours=1))
    db_session.add(upload)
    await db_session.commit()

    async def fake_classify_video_types(client, api_key, video_ids, strict_shorts=False):
        return {}  # nothing came back

    monkeypatch.setattr(youtube_client, "classify_video_types", fake_classify_video_types)

    result = await reclassify_service.rescan_recent_uploads(db_session, http_client=None)

    assert result.checked == 1
    assert result.reclassified == 0

    await db_session.refresh(upload)
    assert upload.video_type_verified is False


@pytest.mark.asyncio
async def test_rescan_batches_over_fifty_ids(db_session, monkeypatch):
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="active-1", group="active", key_value_encrypted=encrypt("k")))
    now = datetime.utcnow()
    uploads = [make_upload(channel.id, f"vid{i}", now - timedelta(minutes=i)) for i in range(60)]
    db_session.add_all(uploads)
    await db_session.commit()

    batch_sizes: list[int] = []

    async def fake_classify_video_types(client, api_key, video_ids, strict_shorts=False):
        batch_sizes.append(len(video_ids))
        return {vid: youtube_client.VideoClassification("video", verified=True) for vid in video_ids}

    monkeypatch.setattr(youtube_client, "classify_video_types", fake_classify_video_types)

    result = await reclassify_service.rescan_recent_uploads(db_session, http_client=None)

    assert result.checked == 60
    assert batch_sizes == [50, 10]


@pytest.mark.asyncio
async def test_rescan_raises_quota_exhausted_when_no_active_key_available(db_session):
    channel = await make_channel(db_session)
    upload = make_upload(channel.id, "vid1", datetime.utcnow() - timedelta(hours=1))
    db_session.add(upload)
    await db_session.commit()
    # No ApiKey in the "active" group at all.

    with pytest.raises(key_pool.QuotaExhaustedError):
        await reclassify_service.rescan_recent_uploads(db_session, http_client=None)


@pytest.mark.asyncio
async def test_rescan_commits_progress_before_a_later_batch_fails(db_session, monkeypatch):
    """If quota runs out partway through, whatever was already reclassified
    must stay saved rather than being rolled back — the caller can just
    rescan again later."""
    channel = await make_channel(db_session)
    db_session.add(ApiKey(label="active-1", group="active", key_value_encrypted=encrypt("k")))
    now = datetime.utcnow()
    uploads = [make_upload(channel.id, f"vid{i}", now - timedelta(minutes=i)) for i in range(60)]
    db_session.add_all(uploads)
    await db_session.commit()

    call_count = 0

    async def fake_classify_video_types(client, api_key, video_ids, strict_shorts=False):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise key_pool.QuotaExhaustedError("active")
        return {vid: youtube_client.VideoClassification("short", verified=True) for vid in video_ids}

    monkeypatch.setattr(youtube_client, "classify_video_types", fake_classify_video_types)
    monkeypatch.setattr(
        key_pool,
        "call_with_key_rotation",
        lambda session, group, call: call("fake-key"),
    )

    with pytest.raises(key_pool.QuotaExhaustedError):
        await reclassify_service.rescan_recent_uploads(db_session, http_client=None)

    # Which 50 of the 60 landed in the successful first batch isn't
    # guaranteed (no ORDER BY) — what matters is that exactly one full
    # batch's worth of progress survived the second batch's failure,
    # rather than the whole rescan being rolled back to nothing.
    result = await db_session.execute(select(Upload))
    all_uploads = list(result.scalars())
    succeeded = [u for u in all_uploads if u.video_type == "short" and u.video_type_verified]
    untouched = [u for u in all_uploads if u.video_type == "video" and not u.video_type_verified]
    assert len(succeeded) == 50
    assert len(untouched) == 10
