"""Two in-process scheduled jobs (APScheduler, no Celery/Redis — see
PROJECT_OUTLINE.md §2 "Subscription sync" and §7): a periodic subscription
+ upload sync, and a more frequent backfill-queue worker tick.
"""

import asyncio
import logging

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db import async_session_factory
from app.services.backfill_service import run_worker_tick
from app.services.sync_service import create_and_run_sync

logger = logging.getLogger(__name__)

SYNC_JOB_ID = "sync"
BACKFILL_JOB_ID = "backfill_worker"


class SchedulerState:
    """Tracks whether a sync is currently running so concurrent triggers
    (scheduled + manual "Sync Now") don't overlap, and so GET
    /api/sync/status can report `is_running`."""

    def __init__(self) -> None:
        self.sync_lock = asyncio.Lock()

    @property
    def is_syncing(self) -> bool:
        return self.sync_lock.locked()


async def run_sync_guarded(state: SchedulerState) -> None:
    if state.sync_lock.locked():
        logger.info("sync already running, skipping this trigger")
        return
    async with state.sync_lock:
        async with async_session_factory() as session, httpx.AsyncClient(timeout=30) as client:
            await create_and_run_sync(session, client)


async def _backfill_tick() -> None:
    async with async_session_factory() as session, httpx.AsyncClient(timeout=30) as client:
        await run_worker_tick(session, client)


def create_scheduler(
    state: SchedulerState, sync_interval_minutes: int, backfill_worker_interval_seconds: int
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        run_sync_guarded,
        trigger=IntervalTrigger(minutes=sync_interval_minutes),
        args=[state],
        id=SYNC_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _backfill_tick,
        trigger=IntervalTrigger(seconds=backfill_worker_interval_seconds),
        id=BACKFILL_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    return scheduler


def reschedule_sync_job(scheduler: AsyncIOScheduler, minutes: int) -> None:
    scheduler.reschedule_job(SYNC_JOB_ID, trigger=IntervalTrigger(minutes=minutes))


def reschedule_backfill_job(scheduler: AsyncIOScheduler, seconds: int) -> None:
    scheduler.reschedule_job(BACKFILL_JOB_ID, trigger=IntervalTrigger(seconds=seconds))
