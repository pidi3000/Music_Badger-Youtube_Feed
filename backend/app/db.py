import re
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_config


class Base(DeclarativeBase):
    pass


def _engine_kwargs(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


def _configure_sqlite_connection(dbapi_connection, connection_record) -> None:
    """Runs on every new SQLite connection the pool opens.

    Without this, SQLite defaults to its rollback-journal mode (a write
    holds an exclusive lock on the whole file) with a 0ms busy timeout (a
    second connection hitting that lock fails instantly instead of
    waiting) — so a long-running write, like the subscription/upload sync
    (one connection held open across importing every subscription and
    incrementally syncing every channel, committed only once at the end),
    could make an unrelated request like login fail with "database is
    locked" for its whole duration. WAL mode lets readers proceed
    concurrently with a writer instead of blocking on it; busy_timeout
    covers the remaining writer-vs-writer case (e.g. the sync job and the
    backfill worker ticking around the same time) by waiting and retrying
    for up to 30s instead of failing immediately.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


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
if config.database_url.startswith("sqlite"):
    event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
