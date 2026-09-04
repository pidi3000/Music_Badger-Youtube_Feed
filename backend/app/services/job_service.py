"""Per-channel sync job tracking (app.models.ChannelSyncJob) — one row per
channel, upserted on every incremental API/RSS upload sync attempt, rather
than a full history log, so the Jobs page can show live status for every
channel without unbounded table growth. Combined with BackfillTask and
SyncLog in api.jobs to give one unified view across all activity kinds:
backfill, per-channel API/RSS sync, and subscription import.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Channel, ChannelSyncJob


async def start_channel_sync_job(session: AsyncSession, channel: Channel, method: str) -> ChannelSyncJob:
    result = await session.execute(select(ChannelSyncJob).where(ChannelSyncJob.channel_id == channel.id))
    job = result.scalar_one_or_none()
    if job is None:
        job = ChannelSyncJob(channel_id=channel.id)
        session.add(job)
    job.method = method
    job.status = "running"
    job.new_uploads_count = 0
    job.error = None
    job.started_at = datetime.utcnow()
    job.finished_at = None
    await session.flush()
    return job


async def finish_channel_sync_job(
    session: AsyncSession, job: ChannelSyncJob, *, new_uploads_count: int = 0, error: str | None = None
) -> None:
    job.status = "error" if error else "success"
    job.new_uploads_count = new_uploads_count
    job.error = error
    job.finished_at = datetime.utcnow()
    await session.flush()
