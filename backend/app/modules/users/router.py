from fastapi import APIRouter

from backend.app.core.deps import CurrentUser, Db
from backend.app.core.schemas import Envelope
from backend.app.modules.users import service
from backend.app.modules.users.schemas import UserOut, UserUpdateIn

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=Envelope[UserOut])
async def me(user: CurrentUser, db: Db) -> Envelope[UserOut]:
    return Envelope(data=await service.to_user_out(db, user))


@router.patch("/me", response_model=Envelope[UserOut])
async def update_me(body: UserUpdateIn, user: CurrentUser, db: Db) -> Envelope[UserOut]:
    updated = await service.set_language(db, user, body.language)
    return Envelope(data=await service.to_user_out(db, updated))
