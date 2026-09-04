"""One-off, on-demand reclassification of recently-fetched uploads using
the strict-mode Shorts redirect check (youtube_client.classify_video_types
with strict_shorts=True) — lets someone who just turned on
AppSettings.strict_shorts_detection retroactively fix uploads that were
already classified by the duration-only heuristic before that setting
existed, without waiting for a fresh sync/backfill to touch them again
(uploads are otherwise never re-fetched or overwritten once cached).

Scoped to uploads published in the last RESCAN_WINDOW_DAYS days, not the
whole history, to keep the extra quota/request cost bounded and
predictable — a full-history reclassification would need to walk every
channel's entire cached upload history. Only uploads not already
`video_type_verified` are touched, which also makes this safely
re-runnable: a quota exhaustion partway through leaves already-verified
rows alone on the next attempt (see RescanResult / QuotaExhaustedError
below).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Upload
from app.services import key_pool, youtube_client

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
    result = await session.execute(
        select(Upload).where(Upload.published_at >= cutoff, Upload.video_type_verified.is_(False))
    )
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
        for video_id, classification in classifications.items():
            upload = uploads_by_video_id[video_id]
            if classification.video_type != upload.video_type:
                reclassified += 1
            upload.video_type = classification.video_type
            upload.video_type_verified = classification.verified
        await session.commit()

    return RescanResult(checked=len(uploads_by_video_id), reclassified=reclassified)
