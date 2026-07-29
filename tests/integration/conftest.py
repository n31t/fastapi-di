"""Integration test fixtures: real app, real Postgres, ASGI-level httpx client."""

import pytest
from dishka import make_async_container
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.config import Config, config
from src.ioc import AppProvider
from src.main import create_app


@pytest.fixture
async def app():
    container = make_async_container(AppProvider(), context={Config: config})
    application = create_app(container)
    yield application
    await container.close()


@pytest.fixture
async def client(app):
    # ASGITransport does not run lifespan: the startup DB ping is skipped,
    # but routes hit the real database through the container.
    # base_url MUST be https: auth cookies are set with secure=True, and
    # httpx's cookie jar refuses to send Secure cookies over an http:// URL.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        yield c


@pytest.fixture
async def raw_client(app):
    """Client that surfaces the app's 500 responses instead of re-raising."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        yield c


@pytest.fixture(autouse=True)
async def clean_db(app):
    engine: AsyncEngine = await app.state.dishka_container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE refresh_tokens, users CASCADE"))
    yield
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE refresh_tokens, users CASCADE"))
