from datetime import UTC, datetime
from typing import Literal

from bson import ObjectId
from pymongo import DESCENDING, ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.core.audit import write_audit
from backend.app.core.errors import AppError
from backend.app.db.client import Doc
from backend.app.modules.admin.schemas import AuditLogOut
from backend.app.modules.users.schemas import Role, UserOut, UserStatus, user_out


async def list_users(
    db: AsyncDatabase[Doc], status: UserStatus | None, role: Role | None, limit: int
) -> list[UserOut]:
    query: Doc = {}
    if status:
        query["status"] = status
    if role:
        query["role"] = role
    users = await db.users.find(query).sort("created_at", DESCENDING).to_list(limit)
    org_ids = [u["org_id"] for u in users if u.get("org_id")]
    orgs = {o["_id"]: o for o in await db.organizations.find({"_id": {"$in": org_ids}}).to_list()}
    return [user_out(u, orgs.get(u.get("org_id"))) for u in users]


async def decide(
    db: AsyncDatabase[Doc],
    admin: Doc,
    user_id: ObjectId,
    decision: Literal["active", "rejected"],
    reason: str | None = None,
) -> UserOut:
    now = datetime.now(UTC)
    user = await db.users.find_one_and_update(
        {"_id": user_id, "status": "pending"},
        {"$set": {"status": decision, "updated_at": now, "decided_by": admin["_id"]}},
        return_document=ReturnDocument.AFTER,
    )
    if user is None:
        if await db.users.count_documents({"_id": user_id}, limit=1) == 0:
            raise AppError(404, "not_found", "User not found")
        raise AppError(409, "not_pending", "Only pending accounts can be approved or rejected")

    org = None
    if user.get("org_id"):
        org = await db.organizations.find_one_and_update(
            {"_id": user["org_id"]},
            {"$set": {"status": decision, "updated_at": now}},
            return_document=ReturnDocument.AFTER,
        )
    await write_audit(
        db,
        actor_id=admin["_id"],
        action="user.approve" if decision == "active" else "user.reject",
        target_type="user",
        target_id=user_id,
        details={"role": user["role"], "org_id": str(user["org_id"]) if org else None}
        | ({"reason": reason} if reason else {}),
    )
    return user_out(user, org)


async def list_audit_logs(db: AsyncDatabase[Doc], limit: int) -> list[AuditLogOut]:
    rows = await db.audit_logs.find().sort("created_at", DESCENDING).to_list(limit)
    return [
        AuditLogOut(
            id=str(r["_id"]),
            actor_id=str(r["actor_id"]),
            action=r["action"],
            target_type=r["target_type"],
            target_id=str(r["target_id"]),
            details=r.get("details", {}),
            created_at=r["created_at"],
        )
        for r in rows
    ]
