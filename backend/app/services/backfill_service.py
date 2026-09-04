"""Resumable upload-history backfill queue — PROJECT_OUTLINE.md §7.

Each channel gets one BackfillTask on creation. The worker
(app.services.job_worker) calls `process_task` on a tick, but only once the
UpdateTask queue is empty — see job_worker.run_worker_tick. A task pages
through the API via the shared key pool until either the retention target
is met or the channel's whole history is exhausted. If every key is
quota-exhausted mid-task, the task pauses (`paused_quota`) with its cursor
intact and is retried automatically on a later tick — never restarted from
scratch, never silently dropped. Unlike incremental updates
(app.services.update_service), backfill has no RSS fallback: RSS can't
satisfy a count/date target on its own, since it only ever returns the ~15
most recent items.
"""

import logging
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSettings, BackfillTask, Channel
from app.services import key_pool, youtube_client
from app.services.settings_service import get_or_create_settings
from app.services.upload_store import upsert_uploads

logger = logging.getLogger(__name__)


def _target_after(settings: AppSettings) -> date:
    return (datetime.utcnow() - timedelta(days=settings.backfill_days)).date()


async def enqueue_backfill_task(session: AsyncSession, channel: Channel, settings: AppSettings) -> BackfillTask:
    task = BackfillTask(
        channel_id=channel.id,
        status="queued",
        target_min_count=settings.backfill_min_count,
        target_after=_target_after(settings),
    )
    session.add(task)
    await session.flush()
    return task


async def get_next_runnable_task(session: AsyncSession) -> BackfillTask | None:
    result = await session.execute(
        select(BackfillTask)
        .where(BackfillTask.status.in_(["queued", "paused_quota"]))
        .order_by(BackfillTask.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def process_task(session: AsyncSession, http_client: httpx.AsyncClient, task: BackfillTask) -> None:
    channel = await session.get(Channel, task.channel_id)
    if channel is None:
        task.status = "failed"
        task.last_error = "channel no longer exists"
        await session.commit()
        return

    settings = await get_or_create_settings(session)
    playlist_id = youtube_client.uploads_playlist_id_for_channel(channel.youtube_channel_id)
    target_after_dt = datetime.combine(task.target_after, datetime.min.time())

    task.status = "in_progress"
    task.started_at = task.started_at or datetime.utcnow()
    task.attempts += 1
    await session.flush()

    try:
        while True:
            cursor = task.resume_cursor
            # Request no more than what's still needed to reach
            # target_min_count — a fixed maxResults=50 meant a target of, say,
            # 5 still pulled a full 50-item page on the very first call
            # (YouTube returns whatever the request asks for, not whatever
            # the target needs). Once the count target is already met and
            # we're only still chasing target_after (some channels post
            # often enough that "at least N days back" genuinely needs more
            # than target_min_count items), full 50-item pages are the more
            # efficient choice again.
            remaining = task.target_min_count - task.fetched_count
            page_max_results = min(50, remaining) if remaining > 0 else 50

            async def _call(
                api_key: str, _cursor: str | None = cursor, _max_results: int = page_max_results
            ) -> youtube_client.Page:
                return await youtube_client.list_uploads(
                    http_client,
                    api_key,
                    playlist_id,
                    page_token=_cursor,
                    max_results=_max_results,
                    strict_shorts=settings.strict_shorts_detection,
                )

            page = await key_pool.call_with_key_rotation(session, _call)

            new_count = await upsert_uploads(session, channel, page.items, fetched_via="api")
            task.fetched_count += new_count

            if page.items:
                oldest_in_page = min(item.published_at for item in page.items)
                if task.oldest_fetched_published_at is None or oldest_in_page < task.oldest_fetched_published_at:
                    task.oldest_fetched_published_at = oldest_in_page

            task.resume_cursor = page.next_page_token
            await session.flush()

            target_met = (
                task.fetched_count >= task.target_min_count
                and task.oldest_fetched_published_at is not None
                and task.oldest_fetched_published_at <= target_after_dt
            )
            no_more_pages = page.next_page_token is None

            if target_met or no_more_pages:
                task.status = "completed"
                task.completed_at = datetime.utcnow()
                channel.backfill_completed_at = task.completed_at
                break
    except key_pool.QuotaExhaustedError:
        task.status = "paused_quota"
        logger.info("backfill task %s paused: background key pool exhausted", task.id)
    except Exception as exc:  # noqa: BLE001 - persisted for the progress UI, re-raised is not useful here
        task.status = "failed"
        task.last_error = str(exc)
        logger.exception("backfill task %s failed", task.id)
    finally:
        await session.commit()


async def run_worker_tick(session: AsyncSession, http_client: httpx.AsyncClient, max_tasks: int = 3) -> int:
    """Processes up to `max_tasks` runnable tasks in one tick. Returns how
    many were processed. Called on a schedule by app.scheduler."""

    processed = 0
    for _ in range(max_tasks):
        task = await get_next_runnable_task(session)
        if task is None:
            break
        await process_task(session, http_client, task)
        processed += 1
    return processed
