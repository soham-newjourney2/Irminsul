from datetime import UTC, datetime

from bson import ObjectId
from pymongo import ASCENDING, ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.core.errors import AppError
from backend.app.core.geo import point_out
from backend.app.db.client import Doc
from backend.app.modules.farms.schemas import FarmIn, FarmOut, FarmUpdate


def farm_out(doc: Doc) -> FarmOut:
    return FarmOut(
        id=str(doc["_id"]),
        name=doc["name"],
        district=doc["district"],
        village=doc.get("village"),
        area_acres=doc.get("area_acres"),
        location=point_out(doc["location"]),
        created_at=doc["created_at"],
    )


async def create(db: AsyncDatabase[Doc], farmer: Doc, data: FarmIn) -> FarmOut:
    now = datetime.now(UTC)
    doc: Doc = {
        "schema_version": 1,
        "farmer_id": farmer["_id"],
        "name": data.name.strip(),
        "district": data.district,
        "village": data.village,
        "area_acres": float(data.area_acres) if data.area_acres is not None else None,
        "location": data.location.to_geojson(),
        "is_demo": False,
        "created_at": now,
        "updated_at": now,
    }
    doc["_id"] = (await db.farms.insert_one(doc)).inserted_id
    return farm_out(doc)


async def list_mine(db: AsyncDatabase[Doc], farmer: Doc) -> list[FarmOut]:
    rows = await db.farms.find({"farmer_id": farmer["_id"]}).sort("created_at", ASCENDING).to_list()
    return [farm_out(r) for r in rows]


async def get_owned(db: AsyncDatabase[Doc], farmer: Doc, farm_id: ObjectId) -> Doc:
    farm = await db.farms.find_one({"_id": farm_id, "farmer_id": farmer["_id"]})
    if farm is None:
        raise AppError(404, "not_found", "Farm not found")
    return farm


async def update(
    db: AsyncDatabase[Doc], farmer: Doc, farm_id: ObjectId, data: FarmUpdate
) -> FarmOut:
    changes: Doc = {}
    for field in ("name", "district", "village"):
        value = getattr(data, field)
        if value is not None:
            changes[field] = value
    if data.area_acres is not None:
        changes["area_acres"] = float(data.area_acres)
    if data.location is not None:
        changes["location"] = data.location.to_geojson()
    if not changes:
        return farm_out(await get_owned(db, farmer, farm_id))
    changes["updated_at"] = datetime.now(UTC)
    doc = await db.farms.find_one_and_update(
        {"_id": farm_id, "farmer_id": farmer["_id"]},
        {"$set": changes},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise AppError(404, "not_found", "Farm not found")
    return farm_out(doc)
