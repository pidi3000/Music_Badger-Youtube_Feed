import asyncio
from collections.abc import Callable
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.deps import DbSession, HttpClient, RequireAuth
from app.models import Channel, ChannelTag
from app.schemas import ChannelCreate, ChannelOut, ChannelUpdate
from app.services import key_pool
from app.services.channel_service import (
    ChannelResolveError,
    ChannelSortField,
    UploadStats,
    channel_to_out,
    create_manual_channel,
    get_upload_stats,
    load_channel,
    run_quick_sync_and_enqueue_backfill,
    set_channel_tags,
    sort_channels,
)
from app.services.settings_service import get_or_create_settings

router = APIRouter(prefix="/channels", tags=["channels"], dependencies=[RequireAuth])


def _channel_query():
    return select(Channel).options(
        selectinload(Channel.channel_tags).selectinload(ChannelTag.tag),
        selectinload(Channel.backfill_tasks),
    )


@router.get("", response_model=list[ChannelOut])
async def list_channels(
    session: DbSession,
    tag_id: int | None = None,
    untagged: bool = False,
    source: Literal["manual", "subscription"] | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = None,
    sort: ChannelSortField = "name",
    order: Literal["asc", "desc"] = "asc",
):
    query = _channel_query()
    if tag_id is not None:
        query = query.join(Channel.channel_tags).where(ChannelTag.tag_id == tag_id)
    if untagged:
        query = query.where(~Channel.channel_tags.any())
    if source == "manual":
        query = query.where(Channel.source.in_(["manual", "both"]))
    elif source == "subscription":
        query = query.where(Channel.source.in_(["subscription", "both"]))
    if status_filter is not None:
        query = query.where(Channel.subscription_status == status_filter)
    if search:
        query = query.where(Channel.title.ilike(f"%{search}%"))

    result = await session.execute(query)
    channels = list(result.unique().scalars())
    stats_by_channel = await get_upload_stats(session, [c.id for c in channels])
    channels = sort_channels(channels, stats_by_channel, sort, order)
    await session.commit()
    return [channel_to_out(c, stats_by_channel.get(c.id, UploadStats())) for c in channels]


async def _run_quick_sync_in_background(
    db_session_factory: Callable[[], AsyncSession], channel_id: int
) -> None:
    async with db_session_factory() as session, httpx.AsyncClient(timeout=30) as client:
        channel = await session.get(Channel, channel_id)
        settings = await get_or_create_settings(session)
        if channel is not None:
            await run_quick_sync_and_enqueue_backfill(session, client, channel, settings)


@router.post("", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
async def add_channel(body: ChannelCreate, session: DbSession, http_client: HttpClient, request: Request):
    settings = await get_or_create_settings(session)
    try:
        channel, is_new = await create_manual_channel(session, http_client, settings, body.channel_link, body.tag_ids)
    except ChannelResolveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except key_pool.QuotaExhaustedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no active API key available — add one in Settings and try again",
        ) from exc

    if is_new:
        # Uses the app's own db_session_factory (rather than importing
        # app.db.async_session_factory directly) so this runs against
        # whichever database this app instance is actually using — tests
        # substitute an isolated one, see tests/conftest.py.
        asyncio.create_task(_run_quick_sync_in_background(request.app.state.db_session_factory, channel.id))

    channel = await load_channel(session, channel.id)
    stats = await _stats_for(session, channel.id)
    return channel_to_out(channel, stats)


async def _get_or_404(session: DbSession, channel_id: int) -> Channel:
    channel = await load_channel(session, channel_id)
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="channel not found")
    return channel


async def _stats_for(session: DbSession, channel_id: int) -> UploadStats:
    stats_by_channel = await get_upload_stats(session, [channel_id])
    return stats_by_channel.get(channel_id, UploadStats())


@router.get("/{channel_id}", response_model=ChannelOut)
async def get_channel(channel_id: int, session: DbSession):
    channel = await _get_or_404(session, channel_id)
    stats = await _stats_for(session, channel_id)
    await session.commit()
    return channel_to_out(channel, stats)


@router.patch("/{channel_id}", response_model=ChannelOut)
async def update_channel(channel_id: int, body: ChannelUpdate, session: DbSession):
    channel = await _get_or_404(session, channel_id)

    if body.tag_ids is not None:
        await set_channel_tags(session, channel, body.tag_ids)

    stats = await _stats_for(session, channel_id)
    await session.commit()
    channel = await load_channel(session, channel_id)
    return channel_to_out(channel, stats)


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(channel_id: int, session: DbSession):
    channel = await _get_or_404(session, channel_id)
    await session.delete(channel)
    await session.commit()


@router.post("/{channel_id}/ack-unsubscribe", response_model=ChannelOut)
async def ack_unsubscribe(channel_id: int, session: DbSession):
    channel = await _get_or_404(session, channel_id)
    channel.unsubscribed_ack = True
    stats = await _stats_for(session, channel_id)
    await session.commit()
    channel = await load_channel(session, channel_id)
    return channel_to_out(channel, stats)
