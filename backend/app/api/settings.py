from fastapi import APIRouter

from app.config import get_config
from app.deps import DbSession, RequireAuth
from app.schemas import SettingsOut, SettingsUpdate
from app.services.settings_service import get_or_create_settings

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[RequireAuth])


def _to_out(settings) -> SettingsOut:
    return SettingsOut(
        sync_interval_minutes=get_config().sync_interval_minutes,
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
async def update_settings(body: SettingsUpdate, session: DbSession):
    settings = await get_or_create_settings(session)

    if body.upload_fetch_method is not None:
        settings.upload_fetch_method = body.upload_fetch_method
    if body.backfill_days is not None:
        settings.backfill_days = body.backfill_days
    if body.backfill_min_count is not None:
        settings.backfill_min_count = body.backfill_min_count

    await session.commit()
    await session.refresh(settings)
    return _to_out(settings)
