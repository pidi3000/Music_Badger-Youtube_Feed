"""Regression test for the SQLite "database is locked" bug: a long-running
write (like the subscription/upload sync, which holds one connection open
across importing every subscription and syncing every channel, committing
only once at the end) must not make an unrelated request on another
connection (like login) fail outright. See app.db._configure_sqlite_connection.
"""

import asyncio

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base, _configure_sqlite_connection
from app.models import Channel

# Python's stdlib sqlite3 module has its own default 5s connection timeout
# (independent of SQLite's C-library default of 0, i.e. fail instantly) —
# passing timeout=0 disables that so these tests reproduce/verify against
# SQLite's true default rather than being masked by Python's.
_NO_PYTHON_DEFAULT_TIMEOUT = {"check_same_thread": False, "timeout": 0}


@pytest.mark.asyncio
async def test_baseline_reproduces_database_is_locked_without_the_fix(tmp_path):
    """Confirms the bug this fix addresses is real: with no busy_timeout
    configured, a second writer while another connection holds an
    uncommitted write fails immediately — this is what made login fail
    during the subscription import."""
    db_path = tmp_path / "baseline.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", connect_args=_NO_PYTHON_DEFAULT_TIMEOUT)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Simulates the sync job: a connection that has written but not yet
    # committed.
    writer_a = factory()
    writer_a.add(Channel(youtube_channel_id="UCa", title="A", source="manual"))
    await writer_a.flush()

    with pytest.raises(OperationalError, match="(?i)locked"):
        async with factory() as writer_b:
            writer_b.add(Channel(youtube_channel_id="UCb", title="B", source="manual"))
            await writer_b.commit()

    await writer_a.rollback()
    await writer_a.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_wal_and_busy_timeout_let_a_second_writer_wait_instead_of_failing(tmp_path):
    """Same contention as the baseline above, but through
    _configure_sqlite_connection — the second writer waits and succeeds
    instead of failing outright."""
    db_path = tmp_path / "fixed.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", connect_args=_NO_PYTHON_DEFAULT_TIMEOUT)
    event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    writer_a = factory()
    writer_a.add(Channel(youtube_channel_id="UCa", title="A", source="manual"))
    await writer_a.flush()

    async def second_writer() -> None:
        async with factory() as writer_b:
            writer_b.add(Channel(youtube_channel_id="UCb", title="B", source="manual"))
            await writer_b.commit()

    task = asyncio.create_task(second_writer())
    await asyncio.sleep(0.2)
    await writer_a.commit()
    await writer_a.close()

    await task  # re-raises if the second writer failed instead of waiting

    async with factory() as session:
        result = await session.execute(select(Channel))
        titles = {c.title for c in result.scalars()}
    assert titles == {"A", "B"}

    await engine.dispose()


@pytest.mark.asyncio
async def test_configure_sqlite_connection_sets_expected_pragmas(tmp_path):
    db_path = tmp_path / "pragmas.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", connect_args={"check_same_thread": False})
    event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)

    async with engine.connect() as conn:
        journal_mode = (await conn.exec_driver_sql("PRAGMA journal_mode")).scalar()
        busy_timeout = (await conn.exec_driver_sql("PRAGMA busy_timeout")).scalar()
        foreign_keys = (await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar()

    assert journal_mode.lower() == "wal"
    assert busy_timeout == 30000
    assert foreign_keys == 1

    await engine.dispose()
