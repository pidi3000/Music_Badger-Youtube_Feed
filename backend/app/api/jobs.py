"""Unified, read-only view across every kind of background activity —
backfill tasks, per-channel incremental upload updates, and subscription
imports — for the Jobs page. Actions (retry) stay on their own
resource-specific routes (POST /api/backfill-tasks/{id}/retry); this router
only aggregates, filters, and sorts them for display.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import DbSession, RequireAuth
from app.models import BackfillTask, SyncLog, UpdateTask
from app.schemas import JobKind, JobOut, JobState
from app.services.channel_service import channel_to_ref

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[RequireAuth])

# Maps every raw status a BackfillTask/UpdateTask/SyncLog can carry onto one
# of the four coarse JobState buckets the Jobs page filters by.
_STATE_GROUPS: dict[str, JobState] = {
    "queued": "queued",
    "in_progress": "running",
    "running": "running",
    "stopping": "running",  # stop requested, still actively winding down
    "completed": "done",
    "success": "done",
    "paused_quota": "stopped",
    "failed": "stopped",
    "error": "stopped",
    "stopped": "stopped",
}

# Statuses a stop request can actually apply to. Anything else (completed,
# failed, etc.) is already finished, and "stopping" itself is a no-op —
# it's already on its way out.
_STOPPABLE_STATUSES = {"queued", "in_progress", "running", "paused_quota"}


def _state_group(status: str) -> JobState | None:
    return _STATE_GROUPS.get(status)


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
async def list_jobs(session: DbSession, limit: int = 100, kind: JobKind | None = None, state: JobState | None = None):
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
    if state is not None:
        jobs = [j for j in jobs if _state_group(j.status) == state]
    jobs.sort(key=lambda j: j.finished_at or j.started_at, reverse=True)
    return jobs[:limit]


@router.post("/{job_id}/stop", response_model=JobOut)
async def stop_job(job_id: str, session: DbSession):
    """Stops a queued job outright, or asks a running one to stop at its
    next safe checkpoint (a page boundary) — see the "stopping" check in
    backfill_service.process_task, update_service.process_task, and
    sync_service._import_subscriptions. `job_id` is the same composite id
    the job list uses (e.g. "backfill-3"), so the frontend never needs to
    know the numeric id or table behind a given row."""

    kind, _, raw_id = job_id.partition("-")
    if not raw_id.isdigit():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    task_id = int(raw_id)

    if kind == "backfill":
        result = await session.execute(
            select(BackfillTask).options(selectinload(BackfillTask.channel)).where(BackfillTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
        if task.status not in _STOPPABLE_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="job is not running or queued")
        task.status = "stopped" if task.status in ("queued", "paused_quota") else "stopping"
        await session.commit()
        await session.refresh(task, attribute_names=["channel"])
        return _backfill_to_job(task)

    if kind == "update":
        result = await session.execute(
            select(UpdateTask).options(selectinload(UpdateTask.channel)).where(UpdateTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
        if task.status not in _STOPPABLE_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="job is not running or queued")
        task.status = "stopped" if task.status in ("queued", "paused_quota") else "stopping"
        await session.commit()
        await session.refresh(task, attribute_names=["channel"])
        return _update_task_to_job(task)

    if kind == "import":
        log = await session.get(SyncLog, task_id)
        if log is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
        if log.status not in _STOPPABLE_STATUSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="job is not running or queued")
        log.status = "stopping"
        await session.commit()
        return _sync_log_to_job(log)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
