from fastapi import APIRouter, Request, Response

from backend.app.config import get_settings
from backend.app.core.deps import Db
from backend.app.core.schemas import Envelope
from backend.app.core.security import create_session_token
from backend.app.db.client import Doc
from backend.app.modules.auth import service
from backend.app.modules.auth.schemas import LoginIn, RegisterIn
from backend.app.modules.users.schemas import UserOut
from backend.app.modules.users.service import to_user_out

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session(response: Response, user: Doc) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        create_session_token(str(user["_id"]), user["role"], settings),
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/register", status_code=201, response_model=Envelope[UserOut])
async def register(body: RegisterIn, response: Response, db: Db) -> Envelope[UserOut]:
    user = await service.register(db, body)
    _set_session(response, user)
    return Envelope(data=await to_user_out(db, user))


@router.post("/login", response_model=Envelope[UserOut])
async def login(body: LoginIn, request: Request, response: Response, db: Db) -> Envelope[UserOut]:
    ip = request.client.host if request.client else "unknown"
    user = await service.login(db, body, ip)
    _set_session(response, user)
    return Envelope(data=await to_user_out(db, user))


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
