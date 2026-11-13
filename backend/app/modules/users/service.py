from collections.abc import Iterable
from datetime import UTC, datetime

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.db.client import Doc
from backend.app.modules.users.schemas import Language, PartyOut, UserOut, user_out


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


async def parties(
    db: AsyncDatabase[Doc], user_ids: Iterable[ObjectId]
) -> dict[ObjectId, tuple[Doc, Doc | None]]:
    """Batch-load users (+ their org) for counterparty views."""
    ids = list({i for i in user_ids if i is not None})
    users = await db.users.find({"_id": {"$in": ids}}, {"password_hash": 0}).to_list()
    org_ids = [u["org_id"] for u in users if u.get("org_id")]
    orgs = {o["_id"]: o for o in await db.organizations.find({"_id": {"$in": org_ids}}).to_list()}
    return {u["_id"]: (u, orgs.get(u.get("org_id"))) for u in users}


def party_out(
    entry: tuple[Doc, Doc | None] | None, *, reveal: bool, district: str | None = None
) -> PartyOut | None:
    if entry is None:
        return None
    user, org = entry
    return PartyOut(
        id=str(user["_id"]),
        name=user["name"],
        org_name=org["name"] if org else None,
        district=district,
        phone=user["phone"] if reveal else None,
    )
