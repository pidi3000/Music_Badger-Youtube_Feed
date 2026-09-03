"""Shared, idempotent Upload persistence — used by both the incremental
sync (app.services.sync_service) and the backfill queue
(app.services.backfill_service) so every fetched upload is cached exactly
once, per PROJECT_OUTLINE.md §7.
"""

from typing import Literal, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, Upload


@runtime_checkable
class UploadEntryLike(Protocol):
    video_id: str
    title: str
    thumbnail_url: str | None
    published_at: object  # datetime, kept loose to avoid importing datetime just for typing
    video_type: str
    video_type_verified: bool


async def upsert_uploads(
    session: AsyncSession,
    channel: Channel,
    entries: list,
    fetched_via: Literal["api", "rss"],
) -> int:
    """Inserts any entries not already cached for this channel. Returns the
    count of newly-inserted rows (already-cached entries are skipped, never
    re-fetched or overwritten — nothing is ever pruned, see §7)."""

    if not entries:
        return 0

    existing_ids = await session.execute(
        select(Upload.youtube_video_id).where(
            Upload.channel_id == channel.id,
            Upload.youtube_video_id.in_([e.video_id for e in entries]),
        )
    )
    existing_ids = set(existing_ids.scalars())

    new_count = 0
    for entry in entries:
        if entry.video_id in existing_ids:
            continue
        session.add(
            Upload(
                channel_id=channel.id,
                youtube_video_id=entry.video_id,
                title=entry.title,
                published_at=entry.published_at,
                thumbnail_url=entry.thumbnail_url,
                fetched_via=fetched_via,
                video_type=getattr(entry, "video_type", "video"),
                video_type_verified=getattr(entry, "video_type_verified", False),
            )
        )
        existing_ids.add(entry.video_id)
        new_count += 1

    await session.flush()
    return new_count
