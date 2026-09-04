from fastapi import APIRouter, HTTPException, status

from app.deps import DbSession, HttpClient, RequireAuth, SchedulerDep
from app.scheduler import reschedule_backfill_job, reschedule_sync_job
from app.schemas import RescanShortsResult, SettingsOut, SettingsUpdate
from app.services import key_pool
from app.services.reclassify_service import rescan_recent_uploads
from app.services.settings_service import get_or_create_settings

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[RequireAuth])


def _to_out(settings) -> SettingsOut:
    return SettingsOut(
        sync_interval_minutes=settings.sync_interval_minutes,
        backfill_worker_interval_seconds=settings.backfill_worker_interval_seconds,
        upload_fetch_method=settings.upload_fetch_method,
        backfill_days=settings.backfill_days,
        backfill_min_count=settings.backfill_min_count,
        strict_shorts_detection=settings.strict_shorts_detection,
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
    if body.strict_shorts_detection is not None:
        settings.strict_shorts_detection = body.strict_shorts_detection

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


@router.post("/rescan-shorts", response_model=RescanShortsResult)
async def rescan_shorts(session: DbSession, http_client: HttpClient):
    try:
        result = await rescan_recent_uploads(session, http_client)
    except key_pool.QuotaExhaustedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "no active-use API key available — uploads checked so far were still saved, "
                "add a key (or wait for quota to reset) and rescan again"
            ),
        ) from exc
    return RescanShortsResult(checked=result.checked, reclassified=result.reclassified)
