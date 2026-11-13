"""Request dependencies: DB handle, current user, RBAC (planning §3). UI hiding is cosmetic."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, Request
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.config import get_settings
from backend.app.core.errors import AppError
from backend.app.core.security import decode_session_token
from backend.app.db.client import Doc, mongo


async def get_db() -> AsyncDatabase[Doc]:
    if mongo.db is None:
        raise AppError(503, "db_unavailable", "Database is not available")
    return mongo.db


Db = Annotated[AsyncDatabase[Doc], Depends(get_db)]

_UNAUTHENTICATED = AppError(401, "unauthenticated", "Please log in")


async def current_user(request: Request, db: Db) -> Doc:
    """Any logged-in user, whatever their status. Status is re-read from the DB every request."""
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise _UNAUTHENTICATED
    claims = decode_session_token(token, settings)
    if claims is None:
        raise _UNAUTHENTICATED
    try:
        user_id = ObjectId(str(claims["sub"]))
    except InvalidId:
        raise _UNAUTHENTICATED from None
    user = await db.users.find_one({"_id": user_id})
    if user is None or user.get("status") == "rejected":
        raise _UNAUTHENTICATED
    return user


CurrentUser = Annotated[Doc, Depends(current_user)]


async def require_active(user: CurrentUser) -> Doc:
    if user.get("status") != "active":
        raise AppError(403, "account_pending", "Your account is awaiting admin approval")
    return user


ActiveUser = Annotated[Doc, Depends(require_active)]


def require_role(*roles: str) -> Callable[[Doc], Awaitable[Doc]]:
    allowed = frozenset(roles)

    async def dependency(user: ActiveUser) -> Doc:
        if user.get("role") not in allowed:
            raise AppError(403, "forbidden", "You do not have access to this resource")
        return user

    return dependency
