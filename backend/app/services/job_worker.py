"""Orchestrates one worker tick across both per-channel task queues:
UpdateTask (incremental "what's new" sync) and BackfillTask (deep history
backfill). Update tasks always take priority — a channel's backfill must
never delay fresh uploads showing up for every other channel. Only once the
update queue is completely empty (no queued or paused_quota tasks left) does
the backfill queue get a turn on that tick.
"""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import backfill_service, update_service


async def run_worker_tick(session: AsyncSession, http_client: httpx.AsyncClient, max_tasks: int = 3) -> int:
    processed = await update_service.run_worker_tick(session, http_client, max_tasks=max_tasks)
    if processed > 0:
        return processed
    return await backfill_service.run_worker_tick(session, http_client, max_tasks=max_tasks)
