from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_config
from app.models import AppSettings
from app.security import hash_secret


async def get_or_create_settings(session: AsyncSession) -> AppSettings:
    """The single-row Settings table (PROJECT_OUTLINE.md §4). Seeded from
    Config.app_access_secret on first boot."""

    result = await session.execute(select(AppSettings).limit(1))
    settings = result.scalar_one_or_none()
    if settings is not None:
        return settings

    config = get_config()
    settings = AppSettings(
        access_secret_hash=hash_secret(config.app_access_secret),
        sync_interval_minutes=config.sync_interval_minutes,
        backfill_worker_interval_seconds=config.backfill_worker_interval_seconds,
    )
    session.add(settings)
    await session.flush()
    return settings
