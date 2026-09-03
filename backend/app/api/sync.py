import asyncio

import httpx
from fastapi import APIRouter
from sqlalchemy import func, select

from app.db import async_session_factory
from app.deps import DbSession, RequireAuth, SchedulerDep, SchedulerStateDep
from app.models import Channel, SyncLog
from app.scheduler import SYNC_JOB_ID
from app.schemas import SyncLogOut, SyncStatusOut, SyncTriggerResponse
from app.services.sync_service import run_sync

router = APIRouter(prefix="/sync", tags=["sync"], dependencies=[RequireAuth])


async def _run_in_background(log_id: int) -> None:
    async with async_session_factory() as session, httpx.AsyncClient(timeout=30) as client:
        log = await session.get(SyncLog, log_id)
        if log is not None:
            await run_sync(session, client, log)


@router.post("", status_code=202, response_model=SyncTriggerResponse)
async def trigger_sync(session: DbSession, scheduler_state: SchedulerStateDep):
    if scheduler_state.is_syncing:
        result = await session.execute(
            select(SyncLog).where(SyncLog.status == "running").order_by(SyncLog.started_at.desc()).limit(1)
        )
        running_log = result.scalar_one_or_none()
        if running_log is not None:
            return SyncTriggerResponse(sync_log_id=running_log.id, status="started")

    log = SyncLog(status="running")
    session.add(log)
    await session.commit()
    await session.refresh(log)

    async def _guarded() -> None:
        async with scheduler_state.sync_lock:
            await _run_in_background(log.id)

    asyncio.create_task(_guarded())
    return SyncTriggerResponse(sync_log_id=log.id, status="started")


@router.get("/status", response_model=SyncStatusOut)
async def sync_status(session: DbSession, scheduler_state: SchedulerStateDep, scheduler: SchedulerDep):
    result = await session.execute(select(SyncLog).order_by(SyncLog.started_at.desc()).limit(1))
    last_log = result.scalar_one_or_none()

    count_result = await session.execute(
        select(func.count()).select_from(Channel).where(
            Channel.subscription_status == "unsubscribed", Channel.unsubscribed_ack.is_(False)
        )
    )
    unacknowledged_count = count_result.scalar_one()

    job = scheduler.get_job(SYNC_JOB_ID)
    next_run = job.next_run_time.replace(tzinfo=None) if job and job.next_run_time else None

    await session.commit()

    return SyncStatusOut(
        last_sync=SyncLogOut.model_validate(last_log) if last_log else None,
        is_running=scheduler_state.is_syncing,
        next_scheduled_at=next_run,
        unacknowledged_unsubscribed_count=unacknowledged_count,
    )
