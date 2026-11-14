from datetime import UTC, datetime

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from backend.app.core import ratelimit
from backend.app.core.errors import AppError
from backend.app.core.security import hash_password, verify_password
from backend.app.db.client import Doc
from backend.app.modules.auth.schemas import LoginIn, RegisterIn
from backend.app.modules.users.schemas import PENDING_ROLES, normalize_email

_INVALID = AppError(401, "invalid_credentials", "Email or password is incorrect")


async def register(db: AsyncDatabase[Doc], data: RegisterIn) -> Doc:
    now = datetime.now(UTC)
    pending = data.role in PENDING_ROLES
    user: Doc = {
        "schema_version": 1,
        "email": data.email,
        "name": data.name,
        "role": data.role,
        "status": "pending" if pending else "active",
        "language": data.language,
        "password_hash": await hash_password(data.password),
        "org_id": None,
        "created_at": now,
        "updated_at": now,
    }
    try:
        result = await db.users.insert_one(user)
    except DuplicateKeyError:
        raise AppError(409, "email_taken", "An account with this email already exists") from None
    user["_id"] = result.inserted_id

    if pending and data.org_name:
        org = {
            "schema_version": 1,
            "name": data.org_name,
            "kind": data.role,
            "status": "pending",
            "created_by": user["_id"],
            "created_at": now,
            "updated_at": now,
        }
        org_id = (await db.organizations.insert_one(org)).inserted_id
        await db.memberships.insert_one(
            {
                "schema_version": 1,
                "user_id": user["_id"],
                "org_id": org_id,
                "role": "owner",
                "created_at": now,
            }
        )
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"org_id": org_id}})
        user["org_id"] = org_id
    return user


async def login(db: AsyncDatabase[Doc], data: LoginIn, client_ip: str) -> Doc:
    try:
        email = normalize_email(data.email)
    except ValueError:
        raise _INVALID from None
    if not ratelimit.login_ip_limiter.hit(client_ip) or not ratelimit.login_limiter.hit(
        f"{email}|{client_ip}"
    ):
        raise AppError(429, "rate_limited", "Too many login attempts. Try again in a minute")
    user = await db.users.find_one({"email": email})
    password_ok = await verify_password(user["password_hash"] if user else None, data.password)
    if user is None or not password_ok:
        raise _INVALID
    if user["status"] == "rejected":
        raise AppError(403, "account_rejected", "This account registration was rejected")
    return user
