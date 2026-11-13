from datetime import UTC, date, datetime
from typing import Any, Literal

from bson import ObjectId
from pymongo import DESCENDING, ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.core.errors import AppError
from backend.app.core.geo import GeoPoint, point_out
from backend.app.core.schemas import parse_object_id
from backend.app.core.units import rupees_to_paise, to_kg
from backend.app.db.client import Doc
from backend.app.modules.farms.service import get_owned as get_owned_farm
from backend.app.modules.listings.schemas import (
    OPEN_FOR_REQUESTS,
    ListingIn,
    ListingOut,
    ListingUpdate,
)
from backend.app.modules.notifications.service import notify
from backend.app.modules.users.service import parties, party_out

OPEN_ORDER_STATUSES = ("confirmed", "dispatched")
SortKey = Literal["newest", "price", "distance"]


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def listing_out(doc: Doc, viewer: Doc, farmer_entry: Any = None) -> ListingOut:
    return ListingOut(
        id=str(doc["_id"]),
        farmer=party_out(farmer_entry, reveal=False, district=doc["district"]),
        farm_id=str(doc["farm_id"]),
        commodity=doc["commodity"],
        variety=doc.get("variety"),
        grade=doc.get("grade"),
        qty_kg=doc["qty_kg"],
        remaining_kg=doc["remaining_kg"],
        display_unit=doc["display_unit"],
        harvest_date=_d(doc.get("harvest_date")),
        available_from=date.fromisoformat(doc["available_from"]),
        available_until=_d(doc.get("available_until")),
        asking_price_paise_per_quintal=doc["asking_price_paise_per_quintal"],
        district=doc["district"],
        location=point_out(doc["location"]),
        batch_id=str(doc["batch_id"]) if doc.get("batch_id") else None,
        status=doc["status"],
        note=doc.get("note"),
        is_mine=doc["farmer_id"] == viewer["_id"],
        is_demo=doc.get("is_demo", False),
        distance_km=round(doc["distance_m"] / 1000, 1) if "distance_m" in doc else None,
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


async def _with_farmers(db: AsyncDatabase[Doc], rows: list[Doc], viewer: Doc) -> list[ListingOut]:
    people = await parties(db, (r["farmer_id"] for r in rows))
    return [listing_out(r, viewer, people.get(r["farmer_id"])) for r in rows]


def derive_status(listing: Doc, has_open_orders: bool) -> str:
    """Quantity-driven status. Draft/cancelled/expired are terminal for this calculation."""
    status = listing["status"]
    if status in ("draft", "cancelled", "expired"):
        return status
    remaining, total = listing["remaining_kg"], listing["qty_kg"]
    if remaining >= total:
        return "active"
    if remaining > 0:
        return "partially_fulfilled"
    return "reserved" if has_open_orders else "sold"


async def refresh_status(
    db: AsyncDatabase[Doc], listing_id: ObjectId, session: AsyncClientSession | None = None
) -> Doc | None:
    listing = await db.produce_listings.find_one({"_id": listing_id}, session=session)
    if listing is None:
        return None
    open_orders = await db.orders.count_documents(
        {"listing_id": listing_id, "status": {"$in": list(OPEN_ORDER_STATUSES)}},
        limit=1,
        session=session,
    )
    new_status = derive_status(listing, open_orders > 0)
    if new_status != listing["status"]:
        listing = await db.produce_listings.find_one_and_update(
            {"_id": listing_id},
            {"$set": {"status": new_status, "updated_at": datetime.now(UTC)}},
            return_document=ReturnDocument.AFTER,
            session=session,
        )
    return listing


async def expire_due(db: AsyncDatabase[Doc]) -> None:
    today = datetime.now(UTC).date().isoformat()
    await db.produce_listings.update_many(
        {"status": {"$in": list(OPEN_FOR_REQUESTS)}, "available_until": {"$lt": today}},
        {"$set": {"status": "expired", "updated_at": datetime.now(UTC)}},
    )


async def create(db: AsyncDatabase[Doc], farmer: Doc, data: ListingIn) -> ListingOut:
    farm = await get_owned_farm(db, farmer, parse_object_id(data.farm_id, "farm"))
    try:
        qty_kg = to_kg(data.qty, data.unit)
        price = rupees_to_paise(data.asking_price_per_quintal)
    except ValueError as exc:
        raise AppError(422, "validation_error", str(exc)) from None
    now = datetime.now(UTC)
    doc: Doc = {
        "schema_version": 1,
        "farmer_id": farmer["_id"],
        "farm_id": farm["_id"],
        "commodity": data.commodity,
        "variety": data.variety,
        "grade": data.grade,
        "qty_kg": qty_kg,
        "remaining_kg": qty_kg,
        "display_unit": data.unit,
        "harvest_date": data.harvest_date.isoformat() if data.harvest_date else None,
        "available_from": data.available_from.isoformat(),
        "available_until": data.available_until.isoformat() if data.available_until else None,
        "asking_price_paise_per_quintal": price,
        "currency": "INR",
        "district": farm["district"],
        "location": farm["location"],
        "batch_id": None,
        "status": "active" if data.publish else "draft",
        "note": data.note,
        "is_demo": False,
        "created_at": now,
        "updated_at": now,
    }
    doc["_id"] = (await db.produce_listings.insert_one(doc)).inserted_id
    return (await _with_farmers(db, [doc], farmer))[0]


async def get(db: AsyncDatabase[Doc], viewer: Doc, listing_id: ObjectId) -> ListingOut:
    doc = await db.produce_listings.find_one({"_id": listing_id})
    if doc is None or (doc["status"] == "draft" and doc["farmer_id"] != viewer["_id"]):
        raise AppError(404, "not_found", "Listing not found")
    return (await _with_farmers(db, [doc], viewer))[0]


async def list_mine(db: AsyncDatabase[Doc], farmer: Doc, limit: int) -> list[ListingOut]:
    await expire_due(db)
    rows = (
        await db.produce_listings.find({"farmer_id": farmer["_id"]})
        .sort("created_at", DESCENDING)
        .to_list(limit)
    )
    return await _with_farmers(db, rows, farmer)


async def search(
    db: AsyncDatabase[Doc],
    viewer: Doc,
    *,
    commodity: str | None,
    district: str | None,
    near: GeoPoint | None,
    radius_km: float,
    min_qty_kg: int | None,
    max_price_paise: int | None,
    sort: SortKey,
    limit: int,
) -> list[ListingOut]:
    await expire_due(db)
    query: Doc = {"status": {"$in": list(OPEN_FOR_REQUESTS)}}
    if commodity:
        query["commodity"] = commodity
    if district:
        query["district"] = district
    if min_qty_kg:
        query["remaining_kg"] = {"$gte": min_qty_kg}
    if max_price_paise:
        query["asking_price_paise_per_quintal"] = {"$lte": max_price_paise}

    if near is not None:
        pipeline: list[Doc] = [
            {
                "$geoNear": {
                    "near": near.to_geojson(),
                    "distanceField": "distance_m",
                    "maxDistance": radius_km * 1000,
                    "query": query,
                    "spherical": True,
                }
            }
        ]
        if sort == "price":
            pipeline.append({"$sort": {"asking_price_paise_per_quintal": 1, "distance_m": 1}})
        elif sort == "newest":
            pipeline.append({"$sort": {"created_at": -1}})
        pipeline.append({"$limit": limit})
        rows = await (await db.produce_listings.aggregate(pipeline)).to_list()
    else:
        order = (
            [("asking_price_paise_per_quintal", 1), ("created_at", -1)]
            if sort == "price"
            else [("created_at", -1)]
        )
        rows = await db.produce_listings.find(query).sort(order).to_list(limit)
    return await _with_farmers(db, rows, viewer)


async def _owned(db: AsyncDatabase[Doc], farmer: Doc, listing_id: ObjectId) -> Doc:
    doc = await db.produce_listings.find_one({"_id": listing_id, "farmer_id": farmer["_id"]})
    if doc is None:
        raise AppError(404, "not_found", "Listing not found")
    return doc


async def update(
    db: AsyncDatabase[Doc], farmer: Doc, listing_id: ObjectId, data: ListingUpdate
) -> ListingOut:
    doc = await _owned(db, farmer, listing_id)
    if doc["status"] in ("sold", "expired", "cancelled"):
        raise AppError(409, "listing_closed", "This listing can no longer be edited")
    changes: Doc = {}
    for field in ("variety", "grade", "note"):
        value = getattr(data, field)
        if value is not None:
            changes[field] = value
    if data.available_until is not None:
        if data.available_until.isoformat() < doc["available_from"]:
            raise AppError(422, "validation_error", "available_until is before available_from")
        changes["available_until"] = data.available_until.isoformat()
    if data.asking_price_per_quintal is not None:
        changes["asking_price_paise_per_quintal"] = rupees_to_paise(data.asking_price_per_quintal)
    if changes:
        changes["updated_at"] = datetime.now(UTC)
        await db.produce_listings.update_one({"_id": listing_id}, {"$set": changes})
        doc |= changes
    return (await _with_farmers(db, [doc], farmer))[0]


async def publish(db: AsyncDatabase[Doc], farmer: Doc, listing_id: ObjectId) -> ListingOut:
    await _owned(db, farmer, listing_id)
    doc = await db.produce_listings.find_one_and_update(
        {"_id": listing_id, "status": "draft"},
        {"$set": {"status": "active", "updated_at": datetime.now(UTC)}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise AppError(409, "invalid_transition", "Only draft listings can be published")
    return (await _with_farmers(db, [doc], farmer))[0]


async def cancel(db: AsyncDatabase[Doc], farmer: Doc, listing_id: ObjectId) -> ListingOut:
    """Stops new requests. Existing orders continue; open requests are auto-rejected."""
    await _owned(db, farmer, listing_id)
    now = datetime.now(UTC)
    doc = await db.produce_listings.find_one_and_update(
        {"_id": listing_id, "status": {"$in": ["draft", "active", "partially_fulfilled"]}},
        {"$set": {"status": "cancelled", "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise AppError(409, "invalid_transition", "This listing cannot be cancelled")
    open_reqs = await db.purchase_requests.find(
        {"listing_id": listing_id, "status": {"$in": ["pending", "countered"]}}
    ).to_list()
    if open_reqs:
        await db.purchase_requests.update_many(
            {"_id": {"$in": [r["_id"] for r in open_reqs]}},
            {
                "$set": {
                    "status": "rejected",
                    "updated_at": now,
                    "closed_reason": "listing_cancelled",
                },
                "$push": {"history": {"by": "system", "action": "listing_cancelled", "at": now}},
            },
        )
        await notify(
            db,
            [r["distributor_id"] for r in open_reqs],
            "request.listing_cancelled",
            {"commodity": doc["commodity"]},
            "/distributor/deals.html",
        )
    return (await _with_farmers(db, [doc], farmer))[0]
