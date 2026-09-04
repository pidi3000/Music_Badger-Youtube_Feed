"""Unified, read-only view across every kind of background activity —
backfill tasks, per-channel incremental API/RSS upload syncs, and
subscription imports — for the Jobs page. Actions (retry) stay on their
own resource-specific routes (POST /api/backfill-tasks/{id}/retry); this
router only aggregates and sorts them for display.
"""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import DbSession, RequireAuth
from app.models import BackfillTask, ChannelSyncJob, SyncLog
from app.schemas import JobOut
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


def _sync_job_to_job(job: ChannelSyncJob) -> JobOut:
    detail = None
    if job.status == "success":
        detail = f"{job.new_uploads_count} new upload{'' if job.new_uploads_count == 1 else 's'}"
    return JobOut(
        id=f"sync-{job.id}",
        kind="sync_api" if job.method == "api" else "sync_rss",
        channel=channel_to_ref(job.channel),
        status=job.status,
        detail=detail,
        error=job.error,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _sync_log_to_job(log: SyncLog) -> JobOut:
    return JobOut(
        id=f"import-{log.id}",
        kind="import_subscriptions",
        channel=None,
        status=log.status,
        detail=f"{log.channels_added} added, {log.channels_marked_unsubscribed} unsubscribed",
        error=log.error,
        started_at=log.started_at,
        finished_at=log.finished_at,
    )


@router.get("", response_model=list[JobOut])
async def list_jobs(session: DbSession, limit: int = 100):
    backfill_result = await session.execute(
        select(BackfillTask)
        .options(selectinload(BackfillTask.channel))
        .order_by(BackfillTask.created_at.desc())
        .limit(limit)
    )
    sync_job_result = await session.execute(
        select(ChannelSyncJob)
        .options(selectinload(ChannelSyncJob.channel))
        .order_by(ChannelSyncJob.started_at.desc())
        .limit(limit)
    )
    sync_log_result = await session.execute(select(SyncLog).order_by(SyncLog.started_at.desc()).limit(limit))
    await session.commit()

    jobs = (
        [_backfill_to_job(t) for t in backfill_result.scalars()]
        + [_sync_job_to_job(j) for j in sync_job_result.scalars()]
        + [_sync_log_to_job(log) for log in sync_log_result.scalars()]
    )
    jobs.sort(key=lambda j: j.finished_at or j.started_at, reverse=True)
    return jobs[:limit]
