from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.encryption import encrypt
from app.models import ApiKey
from app.services import key_pool


def make_key(group: str, label: str, status: str = "active") -> ApiKey:
    return ApiKey(label=label, group=group, key_value_encrypted=encrypt(f"secret-{label}"), status=status)


@pytest.mark.asyncio
async def test_get_active_key_respects_group(db_session):
    db_session.add_all(
        [
            make_key("background", "bg-1"),
            make_key("active", "active-1"),
        ]
    )
    await db_session.commit()

    bg_key = await key_pool.get_active_key(db_session, "background")
    active_key = await key_pool.get_active_key(db_session, "active")

    assert bg_key.label == "bg-1"
    assert active_key.label == "active-1"


@pytest.mark.asyncio
async def test_get_active_key_returns_none_when_group_empty(db_session):
    db_session.add(make_key("active", "active-1"))
    await db_session.commit()

    assert await key_pool.get_active_key(db_session, "background") is None


@pytest.mark.asyncio
async def test_call_with_key_rotation_rotates_on_quota_exceeded(db_session):
    db_session.add_all([make_key("background", "bg-1"), make_key("background", "bg-2")])
    await db_session.commit()

    calls: list[str] = []

    async def call(api_key: str) -> str:
        calls.append(api_key)
        if len(calls) == 1:
            raise key_pool.YoutubeQuotaExceeded("quotaExceeded")
        return "ok"

    result = await key_pool.call_with_key_rotation(db_session, "background", call)

    assert result == "ok"
    assert len(calls) == 2

    result = await db_session.execute(select(ApiKey))
    exhausted = [k for k in result.scalars() if k.status == "exhausted"]
    assert len(exhausted) == 1


@pytest.mark.asyncio
async def test_call_with_key_rotation_raises_when_all_keys_exhausted(db_session):
    db_session.add(make_key("background", "bg-1"))
    await db_session.commit()

    async def always_quota_exceeded(api_key: str) -> str:
        raise key_pool.YoutubeQuotaExceeded("quotaExceeded")

    with pytest.raises(key_pool.QuotaExhaustedError):
        await key_pool.call_with_key_rotation(db_session, "background", always_quota_exceeded)


@pytest.mark.asyncio
async def test_call_with_key_rotation_raises_when_group_has_no_keys(db_session):
    async def call(api_key: str) -> str:
        return "unused"

    with pytest.raises(key_pool.QuotaExhaustedError):
        await key_pool.call_with_key_rotation(db_session, "active", call)


@pytest.mark.asyncio
async def test_reactivation_after_quota_reset_time_passes(db_session):
    key = make_key("background", "bg-1", status="exhausted")
    key.quota_resets_at = datetime.utcnow() - timedelta(minutes=1)
    db_session.add(key)
    await db_session.commit()

    active_key = await key_pool.get_active_key(db_session, "background")

    assert active_key is not None
    assert active_key.label == "bg-1"
    assert active_key.status == "active"


@pytest.mark.asyncio
async def test_not_yet_reactivated_before_reset_time(db_session):
    key = make_key("background", "bg-1", status="exhausted")
    key.quota_resets_at = datetime.utcnow() + timedelta(hours=1)
    db_session.add(key)
    await db_session.commit()

    assert await key_pool.get_active_key(db_session, "background") is None


def test_next_quota_reset_is_midnight_pacific_converted_to_utc():
    from zoneinfo import ZoneInfo

    now = datetime(2024, 6, 15, 10, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    reset = key_pool.next_quota_reset_utc(now.astimezone(ZoneInfo("UTC")))

    reset_pacific = reset.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("America/Los_Angeles"))
    assert reset_pacific.hour == 0
    assert reset_pacific.minute == 0
    assert reset_pacific.date() == now.date() + timedelta(days=1)
