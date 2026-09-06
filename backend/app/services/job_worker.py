"""Orchestrates one worker tick across all three queues: ClassificationQueue
(video/short/live classification of already-fetched uploads), UpdateTask
(incremental "what's new" sync) and BackfillTask (deep history backfill).

Classification runs every tick regardless of what else happens — it's
decoupled from fetching precisely so it isn't gated behind (or ahead of)
either task queue, see app.services.classification_service. Update tasks
still always take priority over backfill for the two fetch queues — a
channel's backfill must never delay fresh uploads showing up for every
other channel. Only once the update queue is completely empty (no queued or
paused_quota tasks left) does the backfill queue get a turn on that tick.
"""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import backfill_service, classification_service, update_service


async def run_worker_tick(session: AsyncSession, http_client: httpx.AsyncClient, max_tasks: int = 3) -> int:
    classified = await classification_service.run_worker_tick(session, http_client)

    processed = await update_service.run_worker_tick(session, http_client, max_tasks=max_tasks)
    if processed == 0:
        processed = await backfill_service.run_worker_tick(session, http_client, max_tasks=max_tasks)

    return processed + classified
