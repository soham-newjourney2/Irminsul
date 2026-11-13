"""In-app notifications: stored, then pushed live over the WebSocket hub.

Text is not stored; the UI renders `notifications.<kind>` from the locale with `params`.
"""

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo import DESCENDING
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.core.ws import hub
from backend.app.db.client import Doc
from backend.app.modules.notifications.schemas import NotificationOut

log = logging.getLogger("irminsul.notifications")


def notification_out(doc: Doc) -> NotificationOut:
    return NotificationOut(
        id=str(doc["_id"]),
        kind=doc["kind"],
        params=doc.get("params", {}),
        link=doc.get("link"),
        read=doc.get("read_at") is not None,
        created_at=doc["created_at"],
    )


async def notify(
    db: AsyncDatabase[Doc],
    user_ids: Iterable[ObjectId],
    kind: str,
    params: dict[str, Any] | None = None,
    link: str | None = None,
) -> None:
    """Best effort: a failed notification never fails the business action."""
    ids = list(dict.fromkeys(user_ids))
    if not ids:
        return
    now = datetime.now(UTC)
    docs: list[Doc] = [
        {
            "schema_version": 1,
            "user_id": uid,
            "kind": kind,
            "params": params or {},
            "link": link,
            "read_at": None,
            "created_at": now,
        }
        for uid in ids
    ]
    try:
        await db.notifications.insert_many(docs)
        for doc in docs:
            message = {
                "type": "notification",
                "data": notification_out(doc).model_dump(mode="json"),
            }
            await hub.send_user(str(doc["user_id"]), message)
    except Exception:
        log.exception("Failed to deliver notification %s", kind)


async def org_member_ids(db: AsyncDatabase[Doc], org_id: ObjectId) -> list[ObjectId]:
    rows = await db.users.find({"org_id": org_id, "status": "active"}, {"_id": 1}).to_list()
    return [r["_id"] for r in rows]


async def list_for_user(
    db: AsyncDatabase[Doc], user_id: ObjectId, unread_only: bool, limit: int
) -> tuple[list[NotificationOut], int]:
    query: Doc = {"user_id": user_id}
    if unread_only:
        query["read_at"] = None
    rows = await db.notifications.find(query).sort("created_at", DESCENDING).to_list(limit)
    unread = await db.notifications.count_documents({"user_id": user_id, "read_at": None})
    return [notification_out(r) for r in rows], unread


async def mark_read(db: AsyncDatabase[Doc], user_id: ObjectId, ids: list[ObjectId] | None) -> int:
    query: Doc = {"user_id": user_id, "read_at": None}
    if ids is not None:
        query["_id"] = {"$in": ids}
    result = await db.notifications.update_many(query, {"$set": {"read_at": datetime.now(UTC)}})
    return result.modified_count
