"""Rotates YouTube Data API keys within a group (background/active), per
PROJECT_OUTLINE.md §6: use one key until it's quota-exhausted, then move to
the next active key in the *same* group. Groups never borrow from each
other.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta, timezone
from typing import TypeVar
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.encryption import decrypt
from app.models import ApiKey

T = TypeVar("T")

_PACIFIC = ZoneInfo("America/Los_Angeles")


class QuotaExhaustedError(Exception):
    """Raised when every key in a group is exhausted/disabled."""

    def __init__(self, group: str):
        super().__init__(f"no active API key available in group '{group}'")
        self.group = group


class YoutubeQuotaExceeded(Exception):
    """Raised by the YouTube client wrapper on a 403 quotaExceeded response."""


def next_quota_reset_utc(now: datetime | None = None) -> datetime:
    """YouTube Data API quota resets daily at midnight Pacific time."""
    now_pacific = (now or datetime.now(timezone.utc)).astimezone(_PACIFIC)
    next_midnight_pacific = datetime.combine(
        now_pacific.date() + timedelta(days=1), time.min, tzinfo=_PACIFIC
    )
    return next_midnight_pacific.astimezone(timezone.utc).replace(tzinfo=None)


async def _reactivate_expired_keys(session: AsyncSession, group: str) -> None:
    now = datetime.utcnow()
    result = await session.execute(
        select(ApiKey).where(
            ApiKey.group == group,
            ApiKey.status == "exhausted",
            ApiKey.quota_resets_at.is_not(None),
            ApiKey.quota_resets_at <= now,
        )
    )
    for key in result.scalars():
        key.status = "active"
        key.quota_resets_at = None
    await session.flush()


async def get_active_key(session: AsyncSession, group: str) -> ApiKey | None:
    await _reactivate_expired_keys(session, group)
    result = await session.execute(
        select(ApiKey)
        .where(ApiKey.group == group, ApiKey.status == "active")
        .order_by(ApiKey.last_used_at.asc().nulls_first(), ApiKey.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def mark_key_used(session: AsyncSession, key: ApiKey) -> None:
    key.last_used_at = datetime.utcnow()
    await session.flush()


async def mark_key_exhausted(session: AsyncSession, key: ApiKey) -> None:
    key.status = "exhausted"
    key.quota_resets_at = next_quota_reset_utc()
    await session.flush()


async def call_with_key_rotation(
    session: AsyncSession, group: str, call: Callable[[str], Awaitable[T]]
) -> T:
    """Runs `call(api_key_value)`, rotating through `group`'s pool on quota
    errors. Raises QuotaExhaustedError once every key in the group has been
    tried and exhausted (or none exist)."""

    tried_key_ids: set[int] = set()
    while True:
        key = await get_active_key(session, group)
        if key is None or key.id in tried_key_ids:
            raise QuotaExhaustedError(group)

        tried_key_ids.add(key.id)
        try:
            result = await call(decrypt(key.key_value_encrypted))
        except YoutubeQuotaExceeded:
            await mark_key_exhausted(session, key)
            continue
        else:
            await mark_key_used(session, key)
            return result
