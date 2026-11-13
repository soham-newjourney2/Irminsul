"""Append-only audit log for admin and business-critical actions (planning §3, §11)."""

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.db.client import Doc


async def write_audit(
    db: AsyncDatabase[Doc],
    *,
    actor_id: ObjectId,
    action: str,
    target_type: str,
    target_id: ObjectId,
    details: dict[str, Any] | None = None,
) -> None:
    await db.audit_logs.insert_one(
        {
            "schema_version": 1,
            "actor_id": actor_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "details": details or {},
            "created_at": datetime.now(UTC),
        }
    )
