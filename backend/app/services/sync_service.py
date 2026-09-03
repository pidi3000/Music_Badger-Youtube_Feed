"""Subscription import + unsubscribe detection + incremental upload sync.
PROJECT_OUTLINE.md §5 (unsubscribe handling) and §6 (RSS fallback).

Runs on the scheduler (background key group only — see app.scheduler) or
on-demand via POST /api/sync, which uses the same code path.
"""

import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.encryption import decrypt
from app.models import AppSettings, Channel, SyncLog
from app.services import avatar_store, key_pool, oauth, rss, youtube_client
from app.services.backfill_service import enqueue_backfill_task
from app.services.settings_service import get_or_create_settings
from app.services.upload_store import upsert_uploads
from app.config import get_config

logger = logging.getLogger(__name__)


async def _get_access_token(http_client: httpx.AsyncClient, settings: AppSettings) -> str | None:
    if not settings.youtube_refresh_token_encrypted:
        return None
    refresh_token = decrypt(settings.youtube_refresh_token_encrypted)
    token = await oauth.refresh_access_token(http_client, get_config(), refresh_token)
    return token.access_token


async def _import_subscriptions(
    session: AsyncSession, http_client: httpx.AsyncClient, access_token: str, settings: AppSettings
) -> tuple[int, int]:
    """Returns (channels_added, channels_marked_unsubscribed)."""

    remote_channels: dict[str, youtube_client.SubscriptionEntry] = {}
    page_token: str | None = None
    while True:
        page = await youtube_client.list_my_subscriptions(http_client, access_token, page_token)
        for entry in page.items:
            remote_channels[entry.channel_id] = entry
        page_token = page.next_page_token
        if not page_token:
            break

    result = await session.execute(select(Channel))
    local_channels = {c.youtube_channel_id: c for c in result.scalars()}

    channels_added = 0
    for channel_id, entry in remote_channels.items():
        local = local_channels.get(channel_id)
        if local is None:
            avatar_url = await avatar_store.store_channel_avatar(http_client, channel_id, entry.thumbnail_url)
            new_channel = Channel(
                youtube_channel_id=channel_id,
                title=entry.title,
                thumbnail_url=avatar_url or entry.thumbnail_url,
                source="subscription",
                subscription_status="subscribed",
                subscribed_at=entry.subscribed_at,
            )
            session.add(new_channel)
            await session.flush()
            await enqueue_backfill_task(session, new_channel, settings)
            channels_added += 1
        else:
            if local.source == "manual":
                local.source = "both"
            if local.subscription_status == "unsubscribed":
                local.subscription_status = "subscribed"
                local.unsubscribed_at = None
                local.unsubscribed_ack = False

    channels_unsubscribed = 0
    for channel_id, local in local_channels.items():
        if local.source not in ("subscription", "both"):
            continue
        if local.subscription_status != "subscribed":
            continue
        if channel_id in remote_channels:
            continue
        local.subscription_status = "unsubscribed"
        local.unsubscribed_at = datetime.utcnow()
        local.unsubscribed_ack = False
        channels_unsubscribed += 1

    await session.flush()
    return channels_added, channels_unsubscribed


async def _sync_channel_uploads(
    session: AsyncSession,
    http_client: httpx.AsyncClient,
    channel: Channel,
    settings: AppSettings,
) -> bool:
    """Fetches new uploads for one already-backfilled channel. Returns True
    if it fell back to RSS due to background-key exhaustion."""

    method = channel.upload_fetch_method or settings.upload_fetch_method
    fell_back = False

    if method == "api":
        try:
            await _sync_channel_uploads_via_api(session, http_client, channel)
        except key_pool.QuotaExhaustedError:
            fell_back = True
            await _sync_channel_uploads_via_rss(session, http_client, channel)
    else:
        await _sync_channel_uploads_via_rss(session, http_client, channel)

    channel.last_synced_at = datetime.utcnow()
    await session.flush()
    return fell_back


async def _sync_channel_uploads_via_api(
    session: AsyncSession, http_client: httpx.AsyncClient, channel: Channel
) -> None:
    playlist_id = youtube_client.uploads_playlist_id_for_channel(channel.youtube_channel_id)

    async def _call(api_key: str) -> youtube_client.Page:
        return await youtube_client.list_uploads(http_client, api_key, playlist_id)

    page = await key_pool.call_with_key_rotation(session, "background", _call)
    # The uploads playlist is newest-first: stop as soon as a page yields no
    # new rows, rather than paginating the channel's whole history again.
    await upsert_uploads(session, channel, page.items, fetched_via="api")


async def _sync_channel_uploads_via_rss(
    session: AsyncSession, http_client: httpx.AsyncClient, channel: Channel
) -> None:
    entries = await rss.fetch_uploads_feed(http_client, channel.youtube_channel_id)
    await upsert_uploads(session, channel, entries, fetched_via="rss")


async def run_sync(session: AsyncSession, http_client: httpx.AsyncClient, log: SyncLog) -> SyncLog:
    """Runs a sync into an existing (already-persisted) SyncLog row. See
    `create_and_run_sync` for the common case of creating one too."""

    settings = await get_or_create_settings(session)
    log.status = "error"  # overwritten below on a clean run; a safe default if something throws early

    try:
        access_token = await _get_access_token(http_client, settings)
        if access_token:
            log.channels_added, log.channels_marked_unsubscribed = await _import_subscriptions(
                session, http_client, access_token, settings
            )

        # Every channel gets an incremental "what's new" sync each cycle,
        # regardless of whether its initial backfill has finished — not
        # gated on backfill_completed_at. Backfilling deep history and
        # picking up recent uploads are independent concerns: gating the
        # latter on the former meant a channel showed zero uploads for as
        # long as its backfill hadn't completed, which for an RSS-configured
        # channel with no "background"-group key (backfill always runs via
        # the API, never RSS) meant forever. upsert_uploads is idempotent,
        # so this and the backfill queue can safely both touch the same
        # channel's uploads without duplicating anything.
        #
        # Each channel is synced in its own try/except: one channel's
        # failure (a genuinely broken feed, an unexpected API error) must
        # not abort every other channel still queued for this cycle, nor
        # discard the channels_added/channels_marked_unsubscribed count
        # already recorded above.
        result = await session.execute(select(Channel))
        errors: list[str] = []
        for channel in result.scalars():
            try:
                fell_back = await _sync_channel_uploads(session, http_client, channel, settings)
            except Exception as exc:  # noqa: BLE001 - isolated per channel, recorded below
                errors.append(f"{channel.title} ({channel.youtube_channel_id}): {exc}")
                logger.exception("sync failed for channel %s", channel.youtube_channel_id)
                continue
            if fell_back:
                log.rss_fallback_channels += 1

        log.status = "error" if errors else "success"
        log.error = "; ".join(errors) or None
    except Exception as exc:  # noqa: BLE001 - recorded on the log for the UI/API
        log.status = "error"
        log.error = str(exc)
        logger.exception("sync failed")
    finally:
        log.finished_at = datetime.utcnow()
        settings.last_sync_at = datetime.utcnow()
        await session.commit()

    return log


async def create_and_run_sync(session: AsyncSession, http_client: httpx.AsyncClient) -> SyncLog:
    log = SyncLog(status="running")
    session.add(log)
    await session.flush()
    return await run_sync(session, http_client, log)
