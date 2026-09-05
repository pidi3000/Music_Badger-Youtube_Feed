"""Manual channel add (resolve by video/ID/handle via the shared API key
pool — see PROJECT_OUTLINE.md §6) plus shared Channel <-> ChannelOut
conversion.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AppSettings, Channel, ChannelTag, Tag, Upload
from app.schemas import ChannelOut, ChannelRef, TagOut
from app.services import avatar_store, key_pool, update_service, youtube_client
from app.services.backfill_service import enqueue_backfill_task
from app.services.channel_parser import ChannelLinkParseError, parse_channel_link


class ChannelResolveError(ValueError):
    pass


async def _resolve_channel_info(
    session: AsyncSession, http_client: httpx.AsyncClient, channel_link: str
) -> youtube_client.ChannelInfo:
    try:
        parsed = parse_channel_link(channel_link)
    except ChannelLinkParseError as exc:
        raise ChannelResolveError(str(exc)) from exc

    if parsed.kind == "video":

        async def _resolve_id(api_key: str) -> str | None:
            return await youtube_client.resolve_channel_id_by_video(http_client, api_key, parsed.value)

        channel_id = await key_pool.call_with_key_rotation(session, _resolve_id)
        if channel_id is None:
            raise ChannelResolveError(f"no YouTube video found for id '{parsed.value}'")

        async def _get(api_key: str) -> youtube_client.ChannelInfo | None:
            return await youtube_client.get_channel(http_client, api_key, channel_id)

        info = await key_pool.call_with_key_rotation(session, _get)

    elif parsed.kind == "channel_id":

        async def _get(api_key: str) -> youtube_client.ChannelInfo | None:
            return await youtube_client.get_channel(http_client, api_key, parsed.value)

        info = await key_pool.call_with_key_rotation(session, _get)

    else:  # handle

        async def _resolve_handle(api_key: str) -> youtube_client.ChannelInfo | None:
            return await youtube_client.resolve_channel_by_handle(http_client, api_key, parsed.value)

        info = await key_pool.call_with_key_rotation(session, _resolve_handle)

    if info is None:
        raise ChannelResolveError(f"could not resolve a YouTube channel from '{channel_link}'")
    return info


async def set_channel_tags(session: AsyncSession, channel: Channel, tag_ids: list[int]) -> None:
    result = await session.execute(select(Tag).where(Tag.id.in_(tag_ids)))
    valid_tag_ids = {tag.id for tag in result.scalars()}

    await session.refresh(channel, attribute_names=["channel_tags"])
    existing = {ct.tag_id: ct for ct in channel.channel_tags}

    for tag_id in existing:
        if tag_id not in valid_tag_ids:
            await session.delete(existing[tag_id])
    for tag_id in valid_tag_ids:
        if tag_id not in existing:
            session.add(ChannelTag(channel_id=channel.id, tag_id=tag_id))

    await session.flush()


async def create_manual_channel(
    session: AsyncSession,
    http_client: httpx.AsyncClient,
    settings: AppSettings,
    channel_link: str,
    tag_ids: list[int],
) -> tuple[Channel, bool]:
    """Returns (channel, is_new) — `is_new` tells the caller whether it still
    needs to run quick sync + queue a backfill (see
    `run_quick_sync_and_enqueue_backfill`); an already-existing channel was
    already synced when it was first added, so re-running that here would
    just be wasted work (and duplicate backfill tasks)."""

    info = await _resolve_channel_info(session, http_client, channel_link)

    result = await session.execute(
        select(Channel).where(Channel.youtube_channel_id == info.id)
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        if existing.source == "subscription":
            existing.source = "both"
        await set_channel_tags(session, existing, tag_ids)
        await session.commit()
        await session.refresh(existing)
        return existing, False

    avatar_url = await avatar_store.store_channel_avatar(http_client, info.id, info.thumbnail_url)

    channel = Channel(
        youtube_channel_id=info.id,
        title=info.title,
        handle=info.handle,
        thumbnail_url=avatar_url or info.thumbnail_url,
        source="manual",
        subscription_status="subscribed",
    )
    session.add(channel)
    await session.flush()
    await set_channel_tags(session, channel, tag_ids)
    await session.commit()
    await session.refresh(channel)
    # The channel row now exists and is committed, so the caller can return
    # to the client immediately — quick sync (a network fetch) and backfill
    # queueing happen afterward, out of band, see api/channels.py.
    return channel, True


async def run_quick_sync_and_enqueue_backfill(
    session: AsyncSession, http_client: httpx.AsyncClient, channel: Channel, settings: AppSettings
) -> None:
    """The rest of what a freshly manually-added channel needs — split out
    of `create_manual_channel` so it can run in the background after the
    channel row is already committed and the HTTP response has returned,
    instead of blocking the add-channel request on a network fetch."""

    quick_result = await update_service.fetch_quick_sync(session, http_client, channel.youtube_channel_id, settings)
    await update_service.apply_quick_sync(session, channel, quick_result)
    await enqueue_backfill_task(session, channel, settings)
    await session.commit()


@dataclass(frozen=True)
class UploadStats:
    count: int = 0
    oldest_at: datetime | None = None
    latest_at: datetime | None = None


async def get_upload_stats(session: AsyncSession, channel_ids: list[int]) -> dict[int, UploadStats]:
    """One aggregate query for however many channels are being rendered,
    rather than a per-channel count/min/max query — used by both the
    channel list and single-channel endpoints."""

    if not channel_ids:
        return {}

    result = await session.execute(
        select(
            Upload.channel_id,
            func.count(Upload.id),
            func.min(Upload.published_at),
            func.max(Upload.published_at),
        )
        .where(Upload.channel_id.in_(channel_ids))
        .group_by(Upload.channel_id)
    )
    return {
        channel_id: UploadStats(count=count, oldest_at=oldest, latest_at=latest)
        for channel_id, count, oldest, latest in result.all()
    }


async def load_channel(session: AsyncSession, channel_id: int) -> Channel | None:
    result = await session.execute(
        select(Channel)
        .where(Channel.id == channel_id)
        .options(
            selectinload(Channel.channel_tags).selectinload(ChannelTag.tag),
            selectinload(Channel.backfill_tasks),
        )
    )
    return result.scalar_one_or_none()


def _backfill_status(channel: Channel) -> str:
    if channel.backfill_completed_at is not None:
        return "completed"
    if not channel.backfill_tasks:
        return "not_started"
    latest = max(channel.backfill_tasks, key=lambda t: t.created_at)
    return latest.status


def channel_to_out(channel: Channel, stats: UploadStats = UploadStats()) -> ChannelOut:
    return ChannelOut(
        id=channel.id,
        youtube_channel_id=channel.youtube_channel_id,
        title=channel.title,
        handle=channel.handle,
        thumbnail_url=channel.thumbnail_url,
        source=channel.source,
        subscription_status=channel.subscription_status,
        unsubscribed_at=channel.unsubscribed_at,
        unsubscribed_ack=channel.unsubscribed_ack,
        backfill_completed_at=channel.backfill_completed_at,
        backfill_status=_backfill_status(channel),
        upload_count=stats.count,
        oldest_upload_at=stats.oldest_at,
        latest_upload_at=stats.latest_at,
        last_synced_at=channel.last_synced_at,
        tags=[TagOut(id=ct.tag.id, name=ct.tag.name, color=ct.tag.color) for ct in channel.channel_tags],
        subscribed_at=channel.subscribed_at,
        added_at=channel.added_at,
        updated_at=channel.updated_at,
    )


def channel_to_ref(channel: Channel) -> ChannelRef:
    return ChannelRef(
        id=channel.id,
        title=channel.title,
        thumbnail_url=channel.thumbnail_url,
        youtube_channel_id=channel.youtube_channel_id,
        handle=channel.handle,
    )


ChannelSortField = Literal["name", "subscribed_at", "latest_upload", "upload_count"]


def sort_channels(
    channels: list[Channel],
    stats_by_channel: dict[int, UploadStats],
    sort: ChannelSortField,
    order: Literal["asc", "desc"],
) -> list[Channel]:
    """Sorted in Python (not SQL) since it needs the aggregated upload
    stats, already computed separately for the list endpoint — channel
    counts are small enough that this is simpler than a SQL-side join."""

    _MIN_DT = datetime.min

    def _key(channel: Channel):
        if sort == "name":
            return channel.title.lower()
        if sort == "subscribed_at":
            return channel.subscribed_at or channel.added_at
        stats = stats_by_channel.get(channel.id, UploadStats())
        if sort == "latest_upload":
            return stats.latest_at or _MIN_DT
        return stats.count  # "upload_count"

    return sorted(channels, key=_key, reverse=(order == "desc"))
