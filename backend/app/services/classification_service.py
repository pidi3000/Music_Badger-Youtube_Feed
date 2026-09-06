"""Background classification of queued uploads — deliberately decoupled
from the fetch that discovers them. See app.services.upload_store.
upsert_uploads and app.models.ClassificationQueue: a newly-fetched page's
uploads used to be classified (including the costly strict-mode Shorts
redirect check) before it was known which of them were actually new,
wasting that work on uploads already cached. Now every new upload is
inserted as "unknown" and queued here; this worker drains the queue in its
own tick, batching up to 50 video ids per `videos.list` call regardless of
which channel or fetch queued them — the same batching efficiency
`videos.list` already offers per page, just no longer wasted on
duplicates or limited to whatever handful of new uploads one channel's one
page happened to contain.

Newest uploads are classified first (`ORDER BY published_at DESC`) so the
Feed's most-recently-published items get a real type/duration as fast as
possible, rather than in arbitrary fetch order.

A "live" or "upcoming" upload's queue row isn't deleted once classified —
its `next_check_at` is pushed out instead, so it gets re-checked later
(has the stream started? ended?) until it settles into "ended".
"""

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClassificationQueue, Upload
from app.services import key_pool, youtube_client
from app.services.settings_service import get_or_create_settings

logger = logging.getLogger(__name__)

# videos.list accepts up to 50 comma-separated ids per call.
BATCH_SIZE = 50

# How long before a still-live or still-upcoming upload gets rechecked,
# rather than left showing stale live/upcoming status forever. A live
# broadcast can end at any moment, so it's rechecked often; a
# scheduled/upcoming stream rarely starts within minutes of being queued,
# so checking it that often would just waste requests.
LIVE_RECHECK_INTERVAL = timedelta(minutes=2)
UPCOMING_RECHECK_INTERVAL = timedelta(minutes=10)


def next_check_at_for(live_status: str | None, now: datetime | None = None) -> datetime | None:
    """When a just-classified upload's queue row should be revisited next.
    None means "done, stop tracking it" — the caller should delete the
    row."""

    now = now or datetime.utcnow()
    if live_status == "live":
        return now + LIVE_RECHECK_INTERVAL
    if live_status == "upcoming":
        return now + UPCOMING_RECHECK_INTERVAL
    return None


async def run_worker_tick(session: AsyncSession, http_client: httpx.AsyncClient, batch_size: int = BATCH_SIZE) -> int:
    """Classifies up to `batch_size` due uploads (newest published_at
    first) in one batched `videos.list` call. Returns how many rows were
    processed — 0 if the queue was empty or no API key was available (a
    quota exhaustion here just leaves the queue as-is for the next tick,
    same as backfill/update tasks pausing on quota)."""

    now = datetime.utcnow()
    result = await session.execute(
        select(ClassificationQueue)
        .where((ClassificationQueue.next_check_at.is_(None)) | (ClassificationQueue.next_check_at <= now))
        .order_by(ClassificationQueue.published_at.desc())
        .limit(batch_size)
    )
    queue_rows = list(result.scalars())
    if not queue_rows:
        return 0

    uploads_result = await session.execute(
        select(Upload).where(Upload.id.in_([row.upload_id for row in queue_rows]))
    )
    uploads_by_id = {u.id: u for u in uploads_result.scalars()}

    live_rows = []
    for row in queue_rows:
        if row.upload_id not in uploads_by_id:
            # The upload itself is gone (e.g. its channel was deleted)
            # since this row was queued — nothing left to classify.
            await session.delete(row)
        else:
            live_rows.append(row)

    if not live_rows:
        await session.commit()
        return 0

    video_ids = [uploads_by_id[row.upload_id].youtube_video_id for row in live_rows]
    settings = await get_or_create_settings(session)

    async def _call(api_key: str) -> dict[str, youtube_client.VideoClassification]:
        return await youtube_client.classify_video_types(
            http_client, api_key, video_ids, strict_shorts=settings.strict_shorts_detection
        )

    try:
        classifications = await key_pool.call_with_key_rotation(session, _call)
    except key_pool.QuotaExhaustedError:
        await session.commit()  # persists the gone-upload cleanup above even though classification didn't run
        logger.info("classification queue tick skipped: no active API key available")
        return 0

    processed = 0
    for row in live_rows:
        upload = uploads_by_id[row.upload_id]
        row.attempts += 1
        classification = classifications.get(upload.youtube_video_id)
        if classification is None:
            # Missing from the videos.list response — a deleted/private
            # video. Stays "unknown"; stop retrying it forever.
            await session.delete(row)
            processed += 1
            continue

        upload.video_type = classification.video_type
        upload.video_type_verified = classification.verified
        upload.duration_seconds = classification.duration_seconds
        upload.live_status = classification.live_status
        upload.scheduled_start_at = classification.scheduled_start_at
        processed += 1

        next_check_at = next_check_at_for(classification.live_status, now)
        if next_check_at is not None:
            row.next_check_at = next_check_at
        else:
            await session.delete(row)

    await session.commit()
    return processed
