"""Resumable per-channel incremental upload sync queue — the counterpart to
backfill_service.py's BackfillTask queue, but for "what's new since last
time" rather than deep history. See app.models.UpdateTask.

Paginates the uploads playlist (newest-first) via the API, stopping as soon
as a page yields no new uploads, there are no more pages, or the oldest
upload fetched so far crosses AppSettings.update_lookback_days — whichever
comes first. If every API key is exhausted mid-task, falls back to RSS (a
single best-effort fetch of the ~15 most recent items) when
AppSettings.rss_fallback_enabled, or pauses (`paused_quota`, resumable from
its cursor) otherwise. A fresh task is enqueued for each channel on every
periodic sync cycle (see sync_service.run_sync), so a channel that fell
back to RSS is naturally retried via the API on the next cycle without any
extra bookkeeping.
"""

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, UpdateTask
from app.services import key_pool, rss, youtube_client
from app.services.settings_service import get_or_create_settings
from app.services.upload_store import upsert_uploads

logger = logging.getLogger(__name__)


async def enqueue_update_task(session: AsyncSession, channel: Channel) -> UpdateTask:
    task = UpdateTask(channel_id=channel.id, status="queued")
    session.add(task)
    await session.flush()
    return task


async def enqueue_update_task_if_needed(session: AsyncSession, channel: Channel) -> UpdateTask | None:
    """Skips enqueueing when the channel already has a pending or running
    task, so a sync cycle shorter than the worker's processing time doesn't
    pile up redundant tasks for the same channel."""

    result = await session.execute(
        select(UpdateTask.id)
        .where(UpdateTask.channel_id == channel.id)
        .where(UpdateTask.status.in_(["queued", "in_progress", "paused_quota"]))
        .limit(1)
    )
    if result.scalar_one_or_none() is not None:
        return None
    return await enqueue_update_task(session, channel)


async def get_next_runnable_task(session: AsyncSession) -> UpdateTask | None:
    result = await session.execute(
        select(UpdateTask)
        .where(UpdateTask.status.in_(["queued", "paused_quota"]))
        .order_by(UpdateTask.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _fall_back_to_rss(
    session: AsyncSession, http_client: httpx.AsyncClient, channel: Channel, task: UpdateTask
) -> None:
    entries = await rss.fetch_uploads_feed(http_client, channel.youtube_channel_id)
    new_count = await upsert_uploads(session, channel, entries, fetched_via="rss")
    task.fetched_count += new_count
    task.used_rss_fallback = True
    task.status = "completed"
    task.completed_at = datetime.utcnow()
    task.resume_cursor = None


async def process_task(
    session: AsyncSession, http_client: httpx.AsyncClient, task: UpdateTask, *, max_pages: int | None = None
) -> None:
    channel = await session.get(Channel, task.channel_id)
    if channel is None:
        task.status = "failed"
        task.last_error = "channel no longer exists"
        await session.commit()
        return

    settings = await get_or_create_settings(session)
    playlist_id = youtube_client.uploads_playlist_id_for_channel(channel.youtube_channel_id)
    lookback_cutoff = datetime.utcnow() - timedelta(days=settings.update_lookback_days)

    task.status = "in_progress"
    task.started_at = task.started_at or datetime.utcnow()
    task.attempts += 1
    await session.flush()

    pages_fetched = 0
    try:
        while True:
            cursor = task.resume_cursor

            async def _call(api_key: str, _cursor: str | None = cursor) -> youtube_client.Page:
                return await youtube_client.list_uploads(
                    http_client,
                    api_key,
                    playlist_id,
                    page_token=_cursor,
                    strict_shorts=settings.strict_shorts_detection,
                )

            try:
                page = await key_pool.call_with_key_rotation(session, _call)
            except key_pool.QuotaExhaustedError:
                if settings.rss_fallback_enabled:
                    await _fall_back_to_rss(session, http_client, channel, task)
                else:
                    task.status = "paused_quota"
                    logger.info("update task %s paused: no active API key available", task.id)
                break

            new_count = await upsert_uploads(session, channel, page.items, fetched_via="api")
            task.fetched_count += new_count
            pages_fetched += 1

            if page.items:
                oldest_in_page = min(item.published_at for item in page.items)
                if task.oldest_fetched_published_at is None or oldest_in_page < task.oldest_fetched_published_at:
                    task.oldest_fetched_published_at = oldest_in_page

            task.resume_cursor = page.next_page_token
            await session.flush()

            no_new_uploads = new_count == 0
            no_more_pages = page.next_page_token is None
            hit_lookback = (
                task.oldest_fetched_published_at is not None
                and task.oldest_fetched_published_at <= lookback_cutoff
            )
            hit_page_limit = max_pages is not None and pages_fetched >= max_pages

            if no_new_uploads or no_more_pages or hit_lookback or hit_page_limit:
                task.status = "completed"
                task.completed_at = datetime.utcnow()
                if no_new_uploads or no_more_pages or hit_lookback:
                    task.resume_cursor = None
                break
    except Exception as exc:  # noqa: BLE001 - persisted for the Jobs page, re-raised is not useful here
        task.status = "failed"
        task.last_error = str(exc)
        logger.exception("update task %s failed", task.id)
    finally:
        channel.last_synced_at = datetime.utcnow()
        await session.commit()


async def run_worker_tick(session: AsyncSession, http_client: httpx.AsyncClient, max_tasks: int = 3) -> int:
    """Processes up to `max_tasks` runnable update tasks in one tick.
    Returns how many were processed. Called by app.services.job_worker."""

    processed = 0
    for _ in range(max_tasks):
        task = await get_next_runnable_task(session)
        if task is None:
            break
        await process_task(session, http_client, task)
        processed += 1
    return processed


async def run_quick_sync(session: AsyncSession, http_client: httpx.AsyncClient, channel: Channel) -> UpdateTask:
    """Runs a single-page update synchronously right after a channel is
    added (manual add or subscription import), so its newest uploads show
    up immediately instead of waiting for the next worker tick."""

    task = await enqueue_update_task(session, channel)
    await process_task(session, http_client, task, max_pages=1)
    return task
