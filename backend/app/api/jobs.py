"""Unified, read-only view across every kind of background activity —
backfill tasks, per-channel incremental upload updates, and subscription
imports — for the Jobs page. Actions (retry) stay on their own
resource-specific routes (POST /api/backfill-tasks/{id}/retry); this router
only aggregates, filters, and sorts them for display.
"""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import DbSession, RequireAuth
from app.models import BackfillTask, SyncLog, UpdateTask
from app.schemas import JobKind, JobOut
from app.services.channel_service import channel_to_ref

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[RequireAuth])


def _backfill_to_job(task: BackfillTask) -> JobOut:
    detail = None
    if task.status not in ("failed",):
        detail = f"{task.fetched_count} / {task.target_min_count} uploads"
    return JobOut(
        id=f"backfill-{task.id}",
        kind="backfill",
        channel=channel_to_ref(task.channel),
        status=task.status,
        detail=detail,
        error=task.last_error,
        started_at=task.started_at or task.created_at,
        finished_at=task.completed_at,
        fetched_count=task.fetched_count,
        target_min_count=task.target_min_count,
        backfill_task_id=task.id,
    )


def _update_task_to_job(task: UpdateTask) -> JobOut:
    detail = None
    if task.status == "completed":
        via = " via RSS" if task.used_rss_fallback else ""
        detail = f"{task.fetched_count} new upload{'' if task.fetched_count == 1 else 's'}{via}"
    elif task.fetched_count:
        detail = f"{task.fetched_count} fetched so far"
    return JobOut(
        id=f"update-{task.id}",
        kind="update",
        channel=channel_to_ref(task.channel),
        status=task.status,
        detail=detail,
        error=task.last_error,
        started_at=task.started_at or task.created_at,
        finished_at=task.completed_at,
    )


def _sync_log_to_job(log: SyncLog) -> JobOut:
    # channels_added is incremented (and committed) as each page of
    # subscriptions.list is processed, so it's a live progress count while
    # status="running" — unsubscribe detection can only be computed once
    # every page has been fetched, so that count only appears once finished.
    if log.status == "running":
        detail = f"{log.channels_added} channel{'' if log.channels_added == 1 else 's'} added so far..."
    else:
        detail = f"{log.channels_added} added, {log.channels_marked_unsubscribed} unsubscribed"
    return JobOut(
        id=f"import-{log.id}",
        kind="import_subscriptions",
        channel=None,
        status=log.status,
        detail=detail,
        error=log.error,
        started_at=log.started_at,
        finished_at=log.finished_at,
        # Reuses the same two fields the backfill progress bar uses — known
        # as soon as the first subscriptions.list page comes back (YouTube
        # reports the total up front via pageInfo.totalResults).
        fetched_count=log.subscriptions_processed if log.total_subscriptions is not None else None,
        target_min_count=log.total_subscriptions,
    )


@router.get("", response_model=list[JobOut])
async def list_jobs(session: DbSession, limit: int = 100, kind: JobKind | None = None):
    backfill_result = await session.execute(
        select(BackfillTask)
        .options(selectinload(BackfillTask.channel))
        .order_by(BackfillTask.created_at.desc())
        .limit(limit)
    )
    update_task_result = await session.execute(
        select(UpdateTask)
        .options(selectinload(UpdateTask.channel))
        .order_by(UpdateTask.created_at.desc())
        .limit(limit)
    )
    sync_log_result = await session.execute(select(SyncLog).order_by(SyncLog.started_at.desc()).limit(limit))
    await session.commit()

    jobs = (
        [_backfill_to_job(t) for t in backfill_result.scalars()]
        + [_update_task_to_job(t) for t in update_task_result.scalars()]
        + [_sync_log_to_job(log) for log in sync_log_result.scalars()]
    )
    if kind is not None:
        jobs = [j for j in jobs if j.kind == kind]
    jobs.sort(key=lambda j: j.finished_at or j.started_at, reverse=True)
    return jobs[:limit]
