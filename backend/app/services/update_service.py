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
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSettings, Channel, UpdateTask
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


async def process_task(session: AsyncSession, http_client: httpx.AsyncClient, task: UpdateTask) -> None:
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

    try:
        while True:
            # Picks up a stop request made from a different session/request
            # while this loop was mid-flight — see api/jobs.py's stop_job.
            # The commit at the bottom of the previous iteration (or the
            # flush just above, for the very first one) is what makes an
            # external "stopping" write visible here.
            if task.status in ("stopping", "stopped"):
                # Also treated as "stopped" already set directly (a narrow
                # race: the stop request read status="queued" and wrote
                # "stopped" straight away just as this loop's own
                # transition to "in_progress" committed) — never overwrite
                # an external stop with our own progress either way.
                task.status = "stopped"
                break

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

            if page.items:
                oldest_in_page = min(item.published_at for item in page.items)
                if task.oldest_fetched_published_at is None or oldest_in_page < task.oldest_fetched_published_at:
                    task.oldest_fetched_published_at = oldest_in_page

            task.resume_cursor = page.next_page_token

            no_new_uploads = new_count == 0
            no_more_pages = page.next_page_token is None
            hit_lookback = (
                task.oldest_fetched_published_at is not None
                and task.oldest_fetched_published_at <= lookback_cutoff
            )

            if no_new_uploads or no_more_pages or hit_lookback:
                task.status = "completed"
                task.completed_at = datetime.utcnow()
                task.resume_cursor = None
                break

            # Commits (not just flushes) this page's progress and ends the
            # transaction, so the stop-check at the top of the next
            # iteration can actually see a "stopping" write made by a
            # different request in the meantime — see the comment there.
            await session.commit()
            await session.refresh(task, attribute_names=["status"])
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


@dataclass(frozen=True)
class QuickSyncResult:
    items: list  # youtube_client.PlaylistItem (via "api") or rss.RssUploadEntry (via "rss")
    fetched_via: str  # "api" | "rss" | "none" (no key, RSS fallback also disabled/failed)


async def fetch_quick_sync(
    session: AsyncSession, http_client: httpx.AsyncClient, youtube_channel_id: str, settings: AppSettings
) -> QuickSyncResult:
    """Fetches a channel's single newest page of uploads — network only, no
    Channel/Upload/UpdateTask writes. Deliberately split from
    `apply_quick_sync` (below) so a caller creating several channels in one
    batch (see sync_service._import_subscriptions) can run every channel's
    network round-trip *before* writing anything for it, rather than
    holding the DB's write lock open across each one's API/RSS call — a
    lock held that long blocks every other write in the app (settings,
    tags, manual edits) for the whole batch."""

    playlist_id = youtube_client.uploads_playlist_id_for_channel(youtube_channel_id)

    async def _call(api_key: str) -> youtube_client.Page:
        return await youtube_client.list_uploads(
            http_client, api_key, playlist_id, strict_shorts=settings.strict_shorts_detection
        )

    try:
        page = await key_pool.call_with_key_rotation(session, _call)
        return QuickSyncResult(items=page.items, fetched_via="api")
    except key_pool.QuotaExhaustedError:
        if not settings.rss_fallback_enabled:
            return QuickSyncResult(items=[], fetched_via="none")
        entries = await rss.fetch_uploads_feed(http_client, youtube_channel_id)
        return QuickSyncResult(items=entries, fetched_via="rss")


async def apply_quick_sync(session: AsyncSession, channel: Channel, result: QuickSyncResult) -> UpdateTask:
    """Persists an already-fetched `QuickSyncResult` as a completed
    UpdateTask — fast, DB-only, no network — so the channel's newest
    uploads show up immediately without waiting for the next worker tick."""

    fetched_via = "rss" if result.fetched_via == "rss" else "api"
    new_count = await upsert_uploads(session, channel, result.items, fetched_via=fetched_via)
    task = UpdateTask(
        channel_id=channel.id,
        status="completed",
        fetched_count=new_count,
        used_rss_fallback=result.fetched_via == "rss",
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )
    session.add(task)
    channel.last_synced_at = datetime.utcnow()
    await session.flush()
    return task
