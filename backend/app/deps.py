from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Annotated

import httpx
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config, get_config
from app.db import async_session_factory
from app.security import verify_session_token

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from app.scheduler import SchedulerState


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
AppConfig = Annotated[Config, Depends(get_config)]


async def require_auth(request: Request, config: AppConfig) -> None:
    token = request.cookies.get(config.session_cookie_name)
    if not token or not verify_session_token(token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")


RequireAuth = Depends(require_auth)


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


HttpClient = Annotated[httpx.AsyncClient, Depends(get_http_client)]


def get_scheduler_state(request: Request) -> "SchedulerState":
    return request.app.state.scheduler_state


SchedulerStateDep = Annotated["SchedulerState", Depends(get_scheduler_state)]


def get_scheduler(request: Request) -> "AsyncIOScheduler":
    return request.app.state.scheduler


SchedulerDep = Annotated["AsyncIOScheduler", Depends(get_scheduler)]
