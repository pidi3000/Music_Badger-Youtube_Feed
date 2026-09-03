"""Manual channel add (resolve by video/ID/handle, using the **active** key
group so it stays fast regardless of background sync/backfill load — see
PROJECT_OUTLINE.md §6) plus shared Channel <-> ChannelOut conversion.
"""

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AppSettings, Channel, ChannelTag, Tag
from app.schemas import ChannelOut, ChannelRef, TagOut
from app.services import key_pool, youtube_client
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

        channel_id = await key_pool.call_with_key_rotation(session, "active", _resolve_id)
        if channel_id is None:
            raise ChannelResolveError(f"no YouTube video found for id '{parsed.value}'")

        async def _get(api_key: str) -> youtube_client.ChannelInfo | None:
            return await youtube_client.get_channel(http_client, api_key, channel_id)

        info = await key_pool.call_with_key_rotation(session, "active", _get)

    elif parsed.kind == "channel_id":

        async def _get(api_key: str) -> youtube_client.ChannelInfo | None:
            return await youtube_client.get_channel(http_client, api_key, parsed.value)

        info = await key_pool.call_with_key_rotation(session, "active", _get)

    else:  # handle

        async def _resolve_handle(api_key: str) -> youtube_client.ChannelInfo | None:
            return await youtube_client.resolve_channel_by_handle(http_client, api_key, parsed.value)

        info = await key_pool.call_with_key_rotation(session, "active", _resolve_handle)

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
) -> Channel:
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
        return existing

    channel = Channel(
        youtube_channel_id=info.id,
        title=info.title,
        handle=info.handle,
        thumbnail_url=info.thumbnail_url,
        source="manual",
        subscription_status="subscribed",
    )
    session.add(channel)
    await session.flush()
    await enqueue_backfill_task(session, channel, settings)
    await set_channel_tags(session, channel, tag_ids)
    await session.commit()
    await session.refresh(channel)
    return channel


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


def channel_to_out(channel: Channel, settings: AppSettings) -> ChannelOut:
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
        upload_fetch_method=channel.upload_fetch_method,
        effective_fetch_method=channel.upload_fetch_method or settings.upload_fetch_method,
        backfill_completed_at=channel.backfill_completed_at,
        backfill_status=_backfill_status(channel),
        tags=[TagOut(id=ct.tag.id, name=ct.tag.name, color=ct.tag.color) for ct in channel.channel_tags],
        added_at=channel.added_at,
        updated_at=channel.updated_at,
    )


def channel_to_ref(channel: Channel) -> ChannelRef:
    return ChannelRef(id=channel.id, title=channel.title, thumbnail_url=channel.thumbnail_url)
