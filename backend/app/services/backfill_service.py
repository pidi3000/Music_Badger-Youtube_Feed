"""Resumable upload-history backfill queue — PROJECT_OUTLINE.md §7.

Each channel gets one BackfillTask on creation. The worker
(app.services.job_worker) calls `process_task` on a tick, but only once the
UpdateTask queue is empty — see job_worker.run_worker_tick. A task pages
through the API via the shared key pool until it's gone back
AppSettings.upload_retention_days or the channel's whole history is
exhausted — purely a date cutoff, not a count target: nothing published
before that cutoff is ever stored, regardless of how few (or many) uploads
that leaves. If every key is quota-exhausted mid-task, the task pauses
(`paused_quota`) with its cursor intact and is retried automatically on a
later tick — never restarted from scratch, never silently dropped. Unlike
incremental updates (app.services.update_service), backfill has no RSS
fallback: RSS can't satisfy a date target on its own, since it only ever
returns the ~15 most recent items.
"""

import logging
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSettings, BackfillTask, Channel
from app.services import key_pool, youtube_client
from app.services.upload_store import upsert_uploads

logger = logging.getLogger(__name__)


def _target_after(settings: AppSettings) -> date:
    return (datetime.utcnow() - timedelta(days=settings.upload_retention_days)).date()


async def enqueue_backfill_task(session: AsyncSession, channel: Channel, settings: AppSettings) -> BackfillTask:
    task = BackfillTask(
        channel_id=channel.id,
        status="queued",
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

    playlist_id = youtube_client.uploads_playlist_id_for_channel(channel.youtube_channel_id)
    target_after_dt = datetime.combine(task.target_after, datetime.min.time())

    task.status = "in_progress"
    task.started_at = task.started_at or datetime.utcnow()
    task.attempts += 1
    # Commits (not just flushes) this transition before the loop's first
    # network call — a flush leaves the write uncommitted, holding
    # SQLite's write lock for as long as that call takes.
    await session.commit()

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
                )

            page = await key_pool.call_with_key_rotation(session, _call)

            # A page can straddle the retention cutoff (some items newer,
            # some older) — only the in-window ones are ever stored, but the
            # raw page (including anything past the cutoff) is still what
            # decides whether to keep paginating, below.
            in_window_items = [item for item in page.items if item.published_at >= target_after_dt]
            new_count = await upsert_uploads(session, channel, in_window_items, fetched_via="api")
            task.fetched_count += new_count

            if page.items:
                oldest_in_page = min(item.published_at for item in page.items)
                if task.oldest_fetched_published_at is None or oldest_in_page < task.oldest_fetched_published_at:
                    task.oldest_fetched_published_at = oldest_in_page

            task.resume_cursor = page.next_page_token

            hit_retention_cutoff = (
                task.oldest_fetched_published_at is not None
                and task.oldest_fetched_published_at <= target_after_dt
            )
            no_more_pages = page.next_page_token is None

            if hit_retention_cutoff or no_more_pages:
                task.status = "completed"
                task.completed_at = datetime.utcnow()
                channel.backfill_completed_at = task.completed_at
                break

            # Commits (not just flushes) this page's progress and ends the
            # transaction, so the stop-check at the top of the next
            # iteration can actually see a "stopping" write made by a
            # different request in the meantime — see the comment there.
            await session.commit()
            await session.refresh(task, attribute_names=["status"])
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
