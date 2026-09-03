import os
from collections.abc import AsyncIterator

# Must be set before any `app.*` module is imported anywhere (including by
# other test files) since Config is read once and cached.
os.environ.setdefault("APP_ACCESS_SECRET", "test-secret")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("ENCRYPTION_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.main import create_app


@pytest_asyncio.fixture
async def db_session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_session_factory) -> AsyncIterator[AsyncSession]:
    async with db_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def app(db_session_factory):
    application = create_app()
    # Substitutes the isolated per-test SQLite factory for the app's real
    # default (app.db.async_session_factory) — both regular routes
    # (via deps.get_db) and the startup lifespan read this same
    # app.state attribute, so this one line covers both.
    application.state.db_session_factory = db_session_factory
    yield application


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture
async def authed_client(client: AsyncClient) -> AsyncClient:
    response = await client.post("/api/auth/login", json={"secret": "test-secret"})
    assert response.status_code == 200, response.text
    return client
