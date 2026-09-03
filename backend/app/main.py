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
from app.scheduler import SchedulerState, create_scheduler

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=30)
    app.state.scheduler_state = SchedulerState()
    app.state.scheduler = create_scheduler(app.state.scheduler_state)
    app.state.scheduler.start()

    yield

    app.state.scheduler.shutdown(wait=False)
    await app.state.http_client.aclose()


def create_app() -> FastAPI:
    config = get_config()
    app = FastAPI(title="Music Badger", version="3.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

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
