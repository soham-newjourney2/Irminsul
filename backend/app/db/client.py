"""MongoDB Atlas client (PyMongo Async). One client per process, opened in the app lifespan."""

from collections.abc import Awaitable, Callable
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.config import Settings

Doc = dict[str, Any]


class Mongo:
    """Holds the process-wide client. `db` is None when no URI is configured."""

    def __init__(self) -> None:
        self.client: AsyncMongoClient[Doc] | None = None
        self.db: AsyncDatabase[Doc] | None = None

    async def connect(self, settings: Settings, db_name: str | None = None) -> None:
        if settings.mongodb_uri is None:
            return
        self.client = AsyncMongoClient(
            settings.mongodb_uri.get_secret_value(),
            serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
            tz_aware=True,
            appname="irminsul",
        )
        self.db = self.client[db_name or settings.mongodb_db]

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
        self.client = None
        self.db = None

    async def ping(self) -> bool:
        if self.client is None:
            return False
        try:
            await self.client.admin.command("ping")
        except Exception:
            return False
        return True

    async def transaction[T](self, fn: Callable[[AsyncClientSession], Awaitable[T]]) -> T:
        """Run `fn` in a multi-document transaction (retries transient errors)."""
        if self.client is None:
            raise RuntimeError("Database is not connected")
        async with self.client.start_session() as session:
            return await session.with_transaction(lambda s: _as_coroutine(fn(s)))


async def _as_coroutine[T](aw: Awaitable[T]) -> T:
    return await aw


mongo = Mongo()
