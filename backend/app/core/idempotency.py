"""Idempotency-Key support for creates. Keys live 24 h (TTL index)."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

from bson import ObjectId
from fastapi import Header
from pydantic import BaseModel
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from backend.app.core.errors import AppError
from backend.app.db.client import Doc

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", max_length=100)]


async def run_idempotent[M: BaseModel](
    db: AsyncDatabase[Doc],
    *,
    user_id: ObjectId,
    key: str | None,
    scope: str,
    model: type[M],
    fn: Callable[[], Awaitable[M]],
) -> M:
    """Run `fn` once per (user, key). Replays return the stored response."""
    if not key:
        return await fn()
    try:
        await db.idempotency_keys.insert_one(
            {
                "key": key,
                "user_id": user_id,
                "scope": scope,
                "state": "in_progress",
                "created_at": datetime.now(UTC),
            }
        )
        replay = False
    except DuplicateKeyError:
        replay = True
    if replay:
        existing = await db.idempotency_keys.find_one({"key": key, "user_id": user_id})
        if existing is None or existing.get("state") != "done":
            raise AppError(409, "request_in_progress", "This request is already being processed")
        if existing["scope"] != scope:
            raise AppError(422, "idempotency_key_reused", "Idempotency key used for another action")
        return model.model_validate(existing["response"])

    try:
        result = await fn()
    except BaseException:
        await db.idempotency_keys.delete_one({"key": key, "user_id": user_id})
        raise
    await db.idempotency_keys.update_one(
        {"key": key, "user_id": user_id},
        {"$set": {"state": "done", "response": result.model_dump(mode="json")}},
    )
    return result
