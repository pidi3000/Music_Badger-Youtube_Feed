from fastapi import APIRouter

from app.deps import DbSession, RequireAuth, SchedulerDep
from app.scheduler import reschedule_backfill_job, reschedule_sync_job
from app.schemas import SettingsOut, SettingsUpdate
from app.services.settings_service import get_or_create_settings

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[RequireAuth])


def _to_out(settings) -> SettingsOut:
    return SettingsOut(
        sync_interval_minutes=settings.sync_interval_minutes,
        backfill_worker_interval_seconds=settings.backfill_worker_interval_seconds,
        upload_fetch_method=settings.upload_fetch_method,
        backfill_days=settings.backfill_days,
        backfill_min_count=settings.backfill_min_count,
        youtube_connected=settings.youtube_refresh_token_encrypted is not None,
        youtube_channel_title=settings.youtube_channel_title,
    )


@router.get("", response_model=SettingsOut)
async def get_settings(session: DbSession):
    settings = await get_or_create_settings(session)
    await session.commit()
    return _to_out(settings)


@router.patch("", response_model=SettingsOut)
async def update_settings(body: SettingsUpdate, session: DbSession, scheduler: SchedulerDep):
    settings = await get_or_create_settings(session)

    if body.upload_fetch_method is not None:
        settings.upload_fetch_method = body.upload_fetch_method
    if body.backfill_days is not None:
        settings.backfill_days = body.backfill_days
    if body.backfill_min_count is not None:
        settings.backfill_min_count = body.backfill_min_count

    # These two also drive the live APScheduler jobs — a value change here
    # reschedules the already-running job immediately rather than only
    # taking effect on next restart.
    if body.sync_interval_minutes is not None and body.sync_interval_minutes != settings.sync_interval_minutes:
        settings.sync_interval_minutes = body.sync_interval_minutes
        reschedule_sync_job(scheduler, body.sync_interval_minutes)
    if (
        body.backfill_worker_interval_seconds is not None
        and body.backfill_worker_interval_seconds != settings.backfill_worker_interval_seconds
    ):
        settings.backfill_worker_interval_seconds = body.backfill_worker_interval_seconds
        reschedule_backfill_job(scheduler, body.backfill_worker_interval_seconds)

    await session.commit()
    await session.refresh(settings)
    return _to_out(settings)
