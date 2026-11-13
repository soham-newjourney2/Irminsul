from datetime import UTC, datetime

from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.db.client import Doc
from backend.app.modules.users.schemas import Language, UserOut, user_out


async def load_org(db: AsyncDatabase[Doc], user: Doc) -> Doc | None:
    org_id = user.get("org_id")
    return await db.organizations.find_one({"_id": org_id}) if org_id else None


async def to_user_out(db: AsyncDatabase[Doc], user: Doc) -> UserOut:
    return user_out(user, await load_org(db, user))


async def set_language(db: AsyncDatabase[Doc], user: Doc, language: Language) -> Doc:
    updated = await db.users.find_one_and_update(
        {"_id": user["_id"]},
        {"$set": {"language": language, "updated_at": datetime.now(UTC)}},
        return_document=ReturnDocument.AFTER,
    )
    return updated or user
