from collections.abc import AsyncIterator

import httpx
import pytest

from backend.app.config import get_settings
from backend.app.db.client import mongo
from backend.app.main import app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """ASGI client without lifespan: no DB connection unless a test opens one."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def test_db() -> AsyncIterator[None]:
    """Real Atlas connection to the test database; skipped when MONGODB_URI is unset."""
    settings = get_settings()
    if settings.mongodb_uri is None:
        pytest.skip("MONGODB_URI not set")
    await mongo.connect(settings, db_name=settings.mongodb_test_db)
    try:
        yield
    finally:
        if mongo.client is not None:
            await mongo.client.drop_database(settings.mongodb_test_db)
        await mongo.close()
