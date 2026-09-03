from fastapi import APIRouter

from app.api import api_keys, auth, backfill, channels, feed, settings, sync, tags, youtube_auth

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(youtube_auth.router)
api_router.include_router(settings.router)
api_router.include_router(tags.router)
api_router.include_router(channels.router)
api_router.include_router(feed.router)
api_router.include_router(api_keys.router)
api_router.include_router(backfill.router)
api_router.include_router(sync.router)
