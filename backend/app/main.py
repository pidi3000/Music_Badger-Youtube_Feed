import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config import get_config
from app.db import async_session_factory
from app.scheduler import SchedulerState, create_scheduler
from app.services.settings_service import get_or_create_settings

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=30)
    app.state.scheduler_state = SchedulerState()

    # app.state.db_session_factory is set in create_app() (defaulting to
    # the real app.db.async_session_factory) so tests can substitute an
    # isolated one before the lifespan runs — see tests/conftest.py.
    async with app.state.db_session_factory() as session:
        settings = await get_or_create_settings(session)
        sync_interval_minutes = settings.sync_interval_minutes
        backfill_worker_interval_seconds = settings.backfill_worker_interval_seconds
        await session.commit()

    app.state.scheduler = create_scheduler(
        app.state.scheduler_state, sync_interval_minutes, backfill_worker_interval_seconds
    )
    app.state.scheduler.start()

    yield

    app.state.scheduler.shutdown(wait=False)
    await app.state.http_client.aclose()


def create_app() -> FastAPI:
    config = get_config()
    app = FastAPI(title="Music Badger", version="3.0.0", lifespan=lifespan)
    app.state.db_session_factory = async_session_factory

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    media_dir = Path(config.media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    static_dir = Path(config.static_dir)
    if static_dir.is_dir():
        assets_dir = static_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static-assets")

        index_file = static_dir / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            requested = static_dir / full_path
            if full_path and requested.is_file():
                return FileResponse(requested)
            return FileResponse(index_file)

    return app


app = create_app()
