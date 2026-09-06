"""One-off, on-demand full reclassification of recently-fetched uploads
using the strict-mode Shorts redirect check
(youtube_client.classify_video_types with strict_shorts=True, hardcoded —
deliberately independent of AppSettings.strict_shorts_detection, since
pressing "Rescan" is itself an explicit request to run the strict check
regardless of that setting). Lets someone retroactively fix uploads that
were classified before that setting existed, or reload one whose
livestream has since ended, without waiting for a fresh sync/backfill to
touch them again (uploads are otherwise never re-fetched or overwritten
once cached).

Scoped to uploads published in the last RESCAN_WINDOW_DAYS days, not the
whole history, to keep the extra quota/request cost bounded and
predictable — a full-history reclassification would need to walk every
channel's entire cached upload history. Every upload in that window is
reloaded from scratch (type, verified flag, duration, live status) — not
just ones never yet verified — since this is an explicit "redo everything"
action, unlike the classification queue's normal do-it-once-and-move-on
behavior (see app.services.classification_service).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClassificationQueue, Upload
from app.services import key_pool, youtube_client
from app.services.classification_service import next_check_at_for

RESCAN_WINDOW_DAYS = 7

# videos.list accepts up to 50 comma-separated ids per call.
_BATCH_SIZE = 50


@dataclass(frozen=True)
class RescanResult:
    checked: int
    reclassified: int


async def rescan_recent_uploads(session: AsyncSession, http_client: httpx.AsyncClient) -> RescanResult:
    """Commits progress after each batch, so a QuotaExhaustedError raised
    partway through (propagated to the caller) doesn't lose the batches
    that already succeeded — the caller can just try again later."""

    cutoff = datetime.utcnow() - timedelta(days=RESCAN_WINDOW_DAYS)
    result = await session.execute(select(Upload).where(Upload.published_at >= cutoff))
    uploads_by_video_id = {u.youtube_video_id: u for u in result.scalars()}
    if not uploads_by_video_id:
        return RescanResult(checked=0, reclassified=0)

    video_ids = list(uploads_by_video_id.keys())
    reclassified = 0

    for i in range(0, len(video_ids), _BATCH_SIZE):
        batch = video_ids[i : i + _BATCH_SIZE]

        async def _call(api_key: str) -> dict[str, youtube_client.VideoClassification]:
            return await youtube_client.classify_video_types(http_client, api_key, batch, strict_shorts=True)

        classifications = await key_pool.call_with_key_rotation(session, _call)

        batch_upload_ids = [uploads_by_video_id[video_id].id for video_id in classifications]
        queue_result = await session.execute(
            select(ClassificationQueue).where(ClassificationQueue.upload_id.in_(batch_upload_ids))
        )
        queue_rows_by_upload_id = {row.upload_id: row for row in queue_result.scalars()}

        for video_id, classification in classifications.items():
            upload = uploads_by_video_id[video_id]
            if classification.video_type != upload.video_type:
                reclassified += 1
            upload.video_type = classification.video_type
            upload.video_type_verified = classification.verified
            upload.duration_seconds = classification.duration_seconds
            upload.live_status = classification.live_status
            upload.scheduled_start_at = classification.scheduled_start_at

            # This upload was just reclassified here, so the classification
            # queue (if it still had a pending or live/upcoming-recheck row
            # for it) doesn't need to redo the same work again.
            queue_row = queue_rows_by_upload_id.get(upload.id)
            if queue_row is not None:
                next_check_at = next_check_at_for(classification.live_status)
                if next_check_at is not None:
                    queue_row.next_check_at = next_check_at
                else:
                    await session.delete(queue_row)
        await session.commit()

    return RescanResult(checked=len(uploads_by_video_id), reclassified=reclassified)
