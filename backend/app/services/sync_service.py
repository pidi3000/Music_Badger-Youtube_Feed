"""Subscription import + unsubscribe detection + per-channel update-task
enqueueing. PROJECT_OUTLINE.md §5 (unsubscribe handling) and §6 (RSS
fallback).

Runs on the scheduler (see app.scheduler) or on-demand via POST /api/sync,
which uses the same code path. The actual upload fetching for existing
channels happens asynchronously afterward, via the UpdateTask queue
processed by app.services.job_worker — this module only detects what needs
updating and enqueues it, plus runs an immediate one-page "quick sync" for
newly-imported channels so their newest uploads show up right away.
"""

import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.encryption import decrypt
from app.models import AppSettings, Channel, SyncLog
from app.services import avatar_store, oauth, update_service, youtube_client
from app.services.backfill_service import enqueue_backfill_task
from app.services.settings_service import get_or_create_settings
from app.config import get_config

logger = logging.getLogger(__name__)


class SyncStoppedError(Exception):
    """Raised internally when a stop request (see api/jobs.py's stop_job)
    is noticed mid-import, so run_sync can record status="stopped" instead
    of treating it as a failure."""


async def _get_access_token(http_client: httpx.AsyncClient, settings: AppSettings) -> str | None:
    if not settings.youtube_refresh_token_encrypted:
        return None
    refresh_token = decrypt(settings.youtube_refresh_token_encrypted)
    token = await oauth.refresh_access_token(http_client, get_config(), refresh_token)
    return token.access_token


async def _import_subscriptions(
    session: AsyncSession,
    http_client: httpx.AsyncClient,
    access_token: str,
    settings: AppSettings,
    log: SyncLog,
) -> int:
    """Returns channels_marked_unsubscribed. channels_added and
    subscriptions_processed are accumulated directly onto `log` (and
    committed) as each entry is processed, rather than computed once at the
    end — see the commit below for why.

    Commits happen per *entry*, not per page: a new channel needs two
    network round-trips (avatar download, quick-sync fetch) before it can
    be written, and those must never happen while a write from a different
    channel processed earlier in the same page is still sitting
    uncommitted — SQLite only allows one writer at a time, so an open
    write transaction blocks every other write in the app (settings, tags,
    manual edits) for as long as it's held. Keeping each channel's network
    work *before* its one fast write-and-commit burst means the lock is
    only ever held for that instant, never across an HTTP call.
    """

    result = await session.execute(select(Channel))
    local_channels = {c.youtube_channel_id: c for c in result.scalars()}

    remote_channel_ids: set[str] = set()
    page_token: str | None = None
    while True:
        page = await youtube_client.list_my_subscriptions(http_client, access_token, page_token)
        if log.total_subscriptions is None and page.total_results is not None:
            log.total_subscriptions = page.total_results
            await session.commit()

        for entry in page.items:
            # Picks up a stop request made from a different session/request
            # while this loop was mid-flight — see api/jobs.py's stop_job.
            # The commit at the bottom of the previous entry (or of the
            # total_subscriptions write above, for the very first one) is
            # what makes an external "stopping" write visible here.
            await session.refresh(log, attribute_names=["status"])
            if log.status in ("stopping", "stopped"):
                raise SyncStoppedError()

            remote_channel_ids.add(entry.channel_id)
            local = local_channels.get(entry.channel_id)
            if local is None:
                # Network round-trips first, no DB write pending yet.
                avatar_url = await avatar_store.store_channel_avatar(http_client, entry.channel_id, entry.thumbnail_url)
                try:
                    quick_result = await update_service.fetch_quick_sync(
                        session, http_client, entry.channel_id, settings
                    )
                except youtube_client.YoutubeApiError as exc:
                    # A single channel's own API error (e.g. a 404
                    # "playlist not found" — some channels genuinely have
                    # none, or the channel was deleted/terminated) must
                    # never abort the whole import: everything after it in
                    # this page, and every later page, still needs
                    # processing. The channel is still added as a real
                    # subscription with no initial uploads; its BackfillTask
                    # will independently retry (and fail visibly on the
                    # Jobs page, with a Retry button) rather than silently
                    # blocking here forever.
                    logger.warning(
                        "quick sync failed for new subscription %s (%s) — adding it with no initial "
                        "uploads instead of aborting the whole sync: %s",
                        entry.channel_id,
                        entry.title,
                        exc,
                    )
                    quick_result = update_service.QuickSyncResult(items=[], fetched_via="none")

                # Now the fast write-and-commit burst.
                new_channel = Channel(
                    youtube_channel_id=entry.channel_id,
                    title=entry.title,
                    thumbnail_url=avatar_url or entry.thumbnail_url,
                    source="subscription",
                    subscription_status="subscribed",
                    subscribed_at=entry.subscribed_at,
                )
                session.add(new_channel)
                await session.flush()
                quick_task = await update_service.apply_quick_sync(session, new_channel, quick_result)
                if quick_task.used_rss_fallback:
                    log.rss_fallback_channels += 1
                await enqueue_backfill_task(session, new_channel, settings)
                local_channels[entry.channel_id] = new_channel
                log.channels_added += 1
            else:
                if local.source == "manual":
                    local.source = "both"
                if local.subscription_status == "unsubscribed":
                    local.subscription_status = "subscribed"
                    local.unsubscribed_at = None
                    local.unsubscribed_ack = False

            log.subscriptions_processed += 1
            await session.commit()

        page_token = page.next_page_token
        if not page_token:
            break

    channels_unsubscribed = 0
    for channel_id, local in local_channels.items():
        if local.source not in ("subscription", "both"):
            continue
        if local.subscription_status != "subscribed":
            continue
        if channel_id in remote_channel_ids:
            continue
        local.subscription_status = "unsubscribed"
        local.unsubscribed_at = datetime.utcnow()
        local.unsubscribed_ack = False
        channels_unsubscribed += 1

    await session.flush()
    return channels_unsubscribed


async def run_sync(session: AsyncSession, http_client: httpx.AsyncClient, log: SyncLog) -> SyncLog:
    """Runs a sync into an existing (already-persisted) SyncLog row. See
    `create_and_run_sync` for the common case of creating one too."""

    settings: AppSettings | None = None
    try:
        settings = await get_or_create_settings(session)

        access_token = await _get_access_token(http_client, settings)
        if access_token:
            log.channels_marked_unsubscribed = await _import_subscriptions(
                session, http_client, access_token, settings, log
            )

        # Every channel gets an incremental "what's new" update task enqueued
        # each cycle, regardless of whether its initial backfill has
        # finished — not gated on backfill_completed_at. Backfilling deep
        # history and picking up recent uploads are independent concerns:
        # gating the latter on the former meant a channel showed zero
        # uploads for as long as its backfill hadn't completed.
        # upsert_uploads is idempotent, so the update queue and the backfill
        # queue can safely both touch the same channel's uploads without
        # duplicating anything. The tasks themselves are processed
        # separately by app.services.job_worker, not here — this only
        # enqueues.
        result = await session.execute(select(Channel))
        for channel in result.scalars():
            await update_service.enqueue_update_task_if_needed(session, channel)

        log.status = "success"
        log.error = None
    except SyncStoppedError:
        log.status = "stopped"
        log.error = None
        logger.info("sync log %s stopped by request", log.id)
    except Exception as exc:  # noqa: BLE001 - recorded on the log for the UI/API
        log.status = "error"
        log.error = str(exc)
        logger.exception("sync failed")
    finally:
        log.finished_at = datetime.utcnow()
        if settings is not None:
            settings.last_sync_at = datetime.utcnow()
        await session.commit()

    return log


async def create_and_run_sync(session: AsyncSession, http_client: httpx.AsyncClient) -> SyncLog:
    log = SyncLog(status="running")
    session.add(log)
    await session.flush()
    return await run_sync(session, http_client, log)
