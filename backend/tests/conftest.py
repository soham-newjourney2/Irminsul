import itertools
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from backend.app.config import get_settings
from backend.app.core.ratelimit import login_ip_limiter, login_limiter
from backend.app.core.security import create_session_token
from backend.app.db.client import Doc, mongo
from backend.app.db.indexes import ensure_indexes
from backend.app.main import app
from backend.app.modules.screening.service import screening_limiter


def _client(target: FastAPI = app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=target, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """ASGI client without lifespan."""
    async with _client() as c:
        yield c


@pytest.fixture(scope="session")
async def _db_session() -> AsyncIterator[bool]:
    """One connection + index build per run against the test database."""
    settings = get_settings()
    if settings.mongodb_uri is None:
        yield False
        return
    await mongo.connect(settings, db_name=settings.mongodb_test_db)
    assert mongo.db is not None
    await ensure_indexes(mongo.db)
    try:
        yield True
    finally:
        if mongo.client is not None:
            await mongo.client.drop_database(settings.mongodb_test_db)
        await mongo.close()


@pytest.fixture
async def test_db(_db_session: bool) -> AsyncIterator[None]:
    """Real test database; skipped when MONGODB_URI is unset. Collections emptied after."""
    if not _db_session:
        pytest.skip("MONGODB_URI not set")
    login_limiter.reset()
    login_ip_limiter.reset()
    screening_limiter.reset()
    try:
        yield
    finally:
        assert mongo.db is not None
        for name in await mongo.db.list_collection_names():
            await mongo.db[name].delete_many({})


_emails = itertools.count(1)
UserFactory = Callable[..., Awaitable[tuple[httpx.AsyncClient, Doc]]]


@pytest.fixture
async def make_user(test_db: None) -> AsyncIterator[UserFactory]:
    """Insert a user directly and return a client already holding its session cookie."""
    clients: list[httpx.AsyncClient] = []

    async def factory(
        role: str,
        *,
        status: str = "active",
        org_name: str | None = None,
        name: str | None = None,
        target: FastAPI = app,
    ) -> tuple[httpx.AsyncClient, Doc]:
        assert mongo.db is not None
        now = datetime.now(UTC)
        user: Doc = {
            "schema_version": 1,
            "email": f"user{next(_emails)}@test.irminsul.test",
            "name": name or f"Test {role}",
            "role": role,
            "status": status,
            "language": "en",
            "password_hash": None,
            "org_id": None,
            "created_at": now,
            "updated_at": now,
        }
        user["_id"] = (await mongo.db.users.insert_one(user)).inserted_id
        if org_name or role in ("distributor", "storage_operator"):
            org = {
                "schema_version": 1,
                "name": org_name or f"{role} org",
                "kind": role,
                "status": status,
                "created_by": user["_id"],
                "created_at": now,
                "updated_at": now,
            }
            org_id = (await mongo.db.organizations.insert_one(org)).inserted_id
            await mongo.db.users.update_one({"_id": user["_id"]}, {"$set": {"org_id": org_id}})
            user["org_id"] = org_id
        c = _client(target)
        clients.append(c)
        settings = get_settings()
        c.cookies.set(
            settings.session_cookie_name,
            create_session_token(str(user["_id"]), role, settings),
        )
        return c, user

    yield factory
    for c in clients:
        await c.aclose()
