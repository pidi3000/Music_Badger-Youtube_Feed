import re
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_config


class Base(DeclarativeBase):
    pass


def _engine_kwargs(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


def _ensure_sqlite_dir_exists(database_url: str) -> None:
    """Creates the parent directory for a file-based SQLite URL so a fresh
    dev checkout works without a manual `mkdir data` step."""
    match = re.match(r"sqlite\+\w+:///(?!:memory:)(.+)", database_url)
    if not match:
        return
    Path(match.group(1)).parent.mkdir(parents=True, exist_ok=True)


config = get_config()
_ensure_sqlite_dir_exists(config.database_url)
engine = create_async_engine(config.database_url, **_engine_kwargs(config.database_url))
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
