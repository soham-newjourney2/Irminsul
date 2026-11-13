from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.app.core.deps import Db, require_role
from backend.app.core.schemas import Envelope, parse_object_id
from backend.app.db.client import Doc
from backend.app.modules.admin import service
from backend.app.modules.admin.schemas import AuditLogOut, RejectIn
from backend.app.modules.users.schemas import Role, UserOut, UserStatus

router = APIRouter(prefix="/admin", tags=["admin"])
Admin = Annotated[Doc, Depends(require_role("admin"))]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/users", response_model=Envelope[list[UserOut]])
async def list_users(
    admin: Admin,
    db: Db,
    status: UserStatus | None = None,
    role: Role | None = None,
    limit: Limit = 50,
) -> Envelope[list[UserOut]]:
    users = await service.list_users(db, status, role, limit)
    return Envelope(data=users, meta={"count": len(users), "limit": limit})


@router.post("/users/{user_id}/approve", response_model=Envelope[UserOut])
async def approve(user_id: str, admin: Admin, db: Db) -> Envelope[UserOut]:
    oid = parse_object_id(user_id, "user")
    return Envelope(data=await service.decide(db, admin, oid, "active"))


@router.post("/users/{user_id}/reject", response_model=Envelope[UserOut])
async def reject(user_id: str, body: RejectIn, admin: Admin, db: Db) -> Envelope[UserOut]:
    oid = parse_object_id(user_id, "user")
    return Envelope(data=await service.decide(db, admin, oid, "rejected", body.reason))


@router.get("/audit-logs", response_model=Envelope[list[AuditLogOut]])
async def audit_logs(admin: Admin, db: Db, limit: Limit = 50) -> Envelope[list[AuditLogOut]]:
    rows = await service.list_audit_logs(db, limit)
    return Envelope(data=rows, meta={"count": len(rows), "limit": limit})
