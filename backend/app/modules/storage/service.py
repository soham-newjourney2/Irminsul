"""Facilities, zones and bookings.

Capacity invariant: reserved_kg + occupied_kg ≤ capacity_kg, enforced by a
conditional update with $expr inside the same transaction as the booking status change.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from bson import ObjectId
from pymongo import DESCENDING, ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.core.audit import write_audit
from backend.app.core.errors import AppError
from backend.app.core.geo import GeoPoint, point_out
from backend.app.core.schemas import parse_object_id
from backend.app.core.units import to_kg
from backend.app.core.ws import hub
from backend.app.db.client import Doc, mongo
from backend.app.modules.batches.service import emit, owned_open_batch
from backend.app.modules.freshtrack import rules as freshtrack_rules
from backend.app.modules.freshtrack import service as freshtrack_service
from backend.app.modules.notifications.service import notify, org_member_ids
from backend.app.modules.storage.schemas import (
    BookingFacility,
    BookingIn,
    BookingOut,
    FacilityIn,
    FacilityOut,
    FacilityUpdate,
    ResubmitIn,
    ZoneIn,
    ZoneOut,
)
from backend.app.modules.users.service import parties, party_out

FARMER_LINK = "/farmer/storage.html"
OPERATOR_LINK = "/storage/bookings.html"
REVEAL_STATUSES = ("accepted", "checked_in", "released")


def _kg(qty: Decimal, unit: str) -> int:
    try:
        return to_kg(qty, unit)
    except ValueError as exc:
        raise AppError(422, "validation_error", str(exc)) from None


def _free(f: Doc) -> int:
    return f["capacity_kg"] - f["reserved_kg"] - f["occupied_kg"]


# --- facilities ---------------------------------------------------------------


async def _facility_views(
    db: AsyncDatabase[Doc], rows: list[Doc], viewer: Doc
) -> list[FacilityOut]:
    org_ids = list({r["org_id"] for r in rows})
    orgs = {o["_id"]: o for o in await db.organizations.find({"_id": {"$in": org_ids}}).to_list()}
    out = []
    for r in rows:
        mine = viewer.get("org_id") is not None and r["org_id"] == viewer.get("org_id")
        org = orgs.get(r["org_id"])
        out.append(
            FacilityOut(
                id=str(r["_id"]),
                org_name=org["name"] if org else None,
                name=r["name"],
                district=r["district"],
                address=r.get("address"),
                location=point_out(r["location"]),
                commodities=r["commodities"],
                capacity_kg=r["capacity_kg"],
                reserved_kg=r["reserved_kg"],
                occupied_kg=r["occupied_kg"],
                free_kg=_free(r),
                status=r["status"],
                contact_email=r.get("contact_email") if mine else None,
                is_mine=mine,
                is_demo=r.get("is_demo", False),
                distance_km=round(r["distance_m"] / 1000, 1) if "distance_m" in r else None,
                created_at=r["created_at"],
            )
        )
    return out


def capacity_message(f: Doc) -> dict[str, Any]:
    return {
        "type": "facility.capacity",
        "data": {
            "id": str(f["_id"]),
            "capacity_kg": f["capacity_kg"],
            "reserved_kg": f["reserved_kg"],
            "occupied_kg": f["occupied_kg"],
            "free_kg": _free(f),
        },
    }


async def create_facility(db: AsyncDatabase[Doc], operator: Doc, data: FacilityIn) -> FacilityOut:
    if operator.get("org_id") is None:
        raise AppError(409, "no_organization", "Your account has no organisation")
    now = datetime.now(UTC)
    doc: Doc = {
        "schema_version": 1,
        "org_id": operator["org_id"],
        "name": data.name.strip(),
        "district": data.district,
        "address": data.address,
        "location": data.location.to_geojson(),
        "commodities": list(data.commodities),
        "capacity_kg": _kg(data.capacity, data.capacity_unit),
        "reserved_kg": 0,
        "occupied_kg": 0,
        "status": "active",
        "contact_email": data.contact_email,
        "created_by": operator["_id"],
        "is_demo": False,
        "created_at": now,
        "updated_at": now,
    }
    doc["_id"] = (await db.storage_facilities.insert_one(doc)).inserted_id
    return (await _facility_views(db, [doc], operator))[0]


async def _own_facility(db: AsyncDatabase[Doc], operator: Doc, facility_id: ObjectId) -> Doc:
    f = await db.storage_facilities.find_one({"_id": facility_id})
    if f is None or operator.get("org_id") is None or f["org_id"] != operator["org_id"]:
        raise AppError(404, "not_found", "Facility not found")
    return f


async def update_facility(
    db: AsyncDatabase[Doc], operator: Doc, facility_id: ObjectId, data: FacilityUpdate
) -> FacilityOut:
    await _own_facility(db, operator, facility_id)
    changes: Doc = {}
    for field in ("name", "address", "status", "contact_email"):
        value = getattr(data, field)
        if value is not None:
            changes[field] = value
    if data.commodities is not None:
        changes["commodities"] = list(dict.fromkeys(data.commodities))
    query: Doc = {"_id": facility_id}
    if data.capacity is not None:
        cap = _kg(data.capacity, data.capacity_unit)
        changes["capacity_kg"] = cap
        # Never shrink below what is already reserved or occupied.
        query["$expr"] = {"$gte": [cap, {"$add": ["$reserved_kg", "$occupied_kg"]}]}
    changes["updated_at"] = datetime.now(UTC)
    doc = await db.storage_facilities.find_one_and_update(
        query, {"$set": changes}, return_document=ReturnDocument.AFTER
    )
    if doc is None:
        raise AppError(
            409, "capacity_below_usage", "Capacity cannot be less than reserved + occupied"
        )
    if "capacity_kg" in changes:
        await hub.broadcast(capacity_message(doc))
    return (await _facility_views(db, [doc], operator))[0]


async def get_facility(db: AsyncDatabase[Doc], viewer: Doc, facility_id: ObjectId) -> FacilityOut:
    f = await db.storage_facilities.find_one({"_id": facility_id})
    mine = f is not None and f["org_id"] == viewer.get("org_id")
    if f is None or (f["status"] != "active" and not mine):
        raise AppError(404, "not_found", "Facility not found")
    return (await _facility_views(db, [f], viewer))[0]


async def list_my_facilities(db: AsyncDatabase[Doc], operator: Doc) -> list[FacilityOut]:
    if operator.get("org_id") is None:
        return []
    rows = (
        await db.storage_facilities.find({"org_id": operator["org_id"]})
        .sort("created_at", DESCENDING)
        .to_list(100)
    )
    return await _facility_views(db, rows, operator)


async def search_facilities(
    db: AsyncDatabase[Doc],
    viewer: Doc,
    *,
    commodity: str | None,
    district: str | None,
    near: GeoPoint | None,
    radius_km: float,
    min_free_kg: int | None,
    limit: int,
) -> list[FacilityOut]:
    query: Doc = {"status": "active"}
    if commodity:
        query["commodities"] = commodity
    if district:
        query["district"] = district
    free_expr = (
        {
            "$expr": {
                "$gte": [
                    {"$subtract": ["$capacity_kg", {"$add": ["$reserved_kg", "$occupied_kg"]}]},
                    min_free_kg,
                ]
            }
        }
        if min_free_kg
        else None
    )
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
        if free_expr:
            pipeline.append({"$match": free_expr})
        pipeline.append({"$limit": limit})
        rows = await (await db.storage_facilities.aggregate(pipeline)).to_list()
    else:
        if free_expr:
            query |= free_expr
        rows = await db.storage_facilities.find(query).sort("name", 1).to_list(limit)
    return await _facility_views(db, rows, viewer)


# --- zones --------------------------------------------------------------------


def zone_out(z: Doc) -> ZoneOut:
    return ZoneOut(
        id=str(z["_id"]),
        facility_id=str(z["facility_id"]),
        name=z["name"],
        kind=z["kind"],
        commodity=z.get("commodity"),
        rule_profile=z.get("rule_profile"),
        capacity_kg=z.get("capacity_kg"),
        created_at=z["created_at"],
    )


async def create_zone(
    db: AsyncDatabase[Doc], operator: Doc, facility_id: ObjectId, data: ZoneIn
) -> ZoneOut:
    f = await _own_facility(db, operator, facility_id)
    if data.commodity and data.commodity not in f["commodities"]:
        raise AppError(422, "validation_error", "Zone commodity is not handled by this facility")
    if data.rule_profile is not None:
        p = freshtrack_rules.profile(data.rule_profile)
        if p is None or (data.commodity and p["commodity"] != data.commodity):
            raise AppError(422, "validation_error", "Unknown storage profile for this crop")
    cap = _kg(data.capacity, data.capacity_unit) if data.capacity is not None else None
    if cap is not None and cap > f["capacity_kg"]:
        raise AppError(422, "validation_error", "Zone capacity exceeds facility capacity")
    doc: Doc = {
        "schema_version": 1,
        "facility_id": facility_id,
        "name": data.name.strip(),
        "kind": data.kind,
        "commodity": data.commodity,
        "rule_profile": data.rule_profile,
        "capacity_kg": cap,  # informational; the invariant is enforced per facility
        "created_at": datetime.now(UTC),
    }
    doc["_id"] = (await db.storage_zones.insert_one(doc)).inserted_id
    return zone_out(doc)


async def list_zones(db: AsyncDatabase[Doc], facility_id: ObjectId) -> list[ZoneOut]:
    rows = await db.storage_zones.find({"facility_id": facility_id}).sort("name", 1).to_list(200)
    return [zone_out(z) for z in rows]


# --- bookings -----------------------------------------------------------------


async def _booking_views(db: AsyncDatabase[Doc], rows: list[Doc], viewer: Doc) -> list[BookingOut]:
    fac_ids = list({r["facility_id"] for r in rows})
    facs = {
        f["_id"]: f for f in await db.storage_facilities.find({"_id": {"$in": fac_ids}}).to_list()
    }
    orgs = {
        o["_id"]: o
        for o in await db.organizations.find(
            {"_id": {"$in": list({f["org_id"] for f in facs.values()})}}
        ).to_list()
    }
    zone_ids = [r["zone_id"] for r in rows if r.get("zone_id")]
    zones = {z["_id"]: z for z in await db.storage_zones.find({"_id": {"$in": zone_ids}}).to_list()}
    people = await parties(db, (r["farmer_id"] for r in rows))
    out = []
    for r in rows:
        f = facs[r["facility_id"]]
        revealed = r["status"] in REVEAL_STATUSES
        org = orgs.get(f["org_id"])
        zone = zones.get(r.get("zone_id"))
        out.append(
            BookingOut(
                id=str(r["_id"]),
                facility=BookingFacility(
                    id=str(f["_id"]),
                    name=f["name"],
                    district=f["district"],
                    location=point_out(f["location"]),
                    org_name=org["name"] if org else None,
                    contact_email=f.get("contact_email") if revealed else None,
                ),
                farmer=party_out(people.get(r["farmer_id"]), reveal=revealed),
                commodity=r["commodity"],
                qty_kg=r["qty_kg"],
                display_unit=r["display_unit"],
                start_date=date.fromisoformat(r["start_date"]),
                end_date=date.fromisoformat(r["end_date"]),
                listing_id=str(r["listing_id"]) if r.get("listing_id") else None,
                batch_id=str(r["batch_id"]) if r.get("batch_id") else None,
                note=r.get("note"),
                status=r["status"],
                zone_id=str(r["zone_id"]) if r.get("zone_id") else None,
                zone_name=zone["name"] if zone else None,
                history=r.get("history", []),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
        )
    return out


async def create_booking(db: AsyncDatabase[Doc], farmer: Doc, data: BookingIn) -> BookingOut:
    facility_id = parse_object_id(data.facility_id, "facility")
    f = await db.storage_facilities.find_one({"_id": facility_id, "status": "active"})
    if f is None:
        raise AppError(404, "not_found", "Facility not found")
    if data.commodity not in f["commodities"]:
        raise AppError(422, "commodity_not_supported", "This facility does not store that crop")
    qty_kg = _kg(data.qty, data.unit)
    if qty_kg > f["capacity_kg"]:
        raise AppError(409, "insufficient_capacity", "Quantity exceeds the facility's capacity")
    listing_id = None
    if data.listing_id:
        listing_id = parse_object_id(data.listing_id, "listing")
        if (
            await db.produce_listings.count_documents(
                {"_id": listing_id, "farmer_id": farmer["_id"]}, limit=1
            )
            == 0
        ):
            raise AppError(404, "not_found", "Listing not found")
    batch_id = None
    if data.batch_id:
        batch = await owned_open_batch(
            db, farmer, parse_object_id(data.batch_id, "batch"), data.commodity
        )
        if qty_kg > batch["qty_kg"]:
            raise AppError(422, "validation_error", "Booking quantity exceeds the batch quantity")
        batch_id = batch["_id"]
    now = datetime.now(UTC)
    doc: Doc = {
        "schema_version": 1,
        "facility_id": facility_id,
        "org_id": f["org_id"],
        "farmer_id": farmer["_id"],
        "listing_id": listing_id,
        "batch_id": batch_id,
        "commodity": data.commodity,
        "qty_kg": qty_kg,
        "display_unit": data.unit,
        "start_date": data.start_date.isoformat(),
        "end_date": data.end_date.isoformat(),
        "note": data.note,
        "status": "requested",
        "zone_id": None,
        "history": [{"status": "requested", "by": "farmer", "note": data.note, "at": now}],
        "is_demo": False,
        "created_at": now,
        "updated_at": now,
    }
    doc["_id"] = (await db.storage_bookings.insert_one(doc)).inserted_id
    await notify(
        db,
        await org_member_ids(db, f["org_id"]),
        "booking.requested",
        {
            "name": farmer["name"],
            "commodity": data.commodity,
            "qty_kg": qty_kg,
            "facility": f["name"],
        },
        OPERATOR_LINK,
    )
    return (await _booking_views(db, [doc], farmer))[0]


async def list_bookings(
    db: AsyncDatabase[Doc],
    user: Doc,
    status: str | None,
    facility_id: ObjectId | None,
    limit: int,
) -> list[BookingOut]:
    if user["role"] == "farmer":
        query: Doc = {"farmer_id": user["_id"]}
    else:
        if user.get("org_id") is None:
            return []
        query = {"org_id": user["org_id"]}
    if status:
        query["status"] = status
    if facility_id:
        query["facility_id"] = facility_id
    rows = await db.storage_bookings.find(query).sort("updated_at", DESCENDING).to_list(limit)
    return await _booking_views(db, rows, user)


async def _load_booking(db: AsyncDatabase[Doc], user: Doc, booking_id: ObjectId) -> Doc:
    b = await db.storage_bookings.find_one({"_id": booking_id})
    allowed = b is not None and (
        (user["role"] == "farmer" and b["farmer_id"] == user["_id"])
        or (user["role"] == "storage_operator" and b["org_id"] == user.get("org_id"))
    )
    if b is None or not allowed:
        raise AppError(404, "not_found", "Booking not found")
    return b


async def get_booking(db: AsyncDatabase[Doc], user: Doc, booking_id: ObjectId) -> BookingOut:
    return (await _booking_views(db, [await _load_booking(db, user, booking_id)], user))[0]


# action → (allowed from, actor role, target status, facility $inc builder or None)
BOOKING_ACTIONS: dict[str, tuple[tuple[str, ...], str, str]] = {
    "accept": (("requested",), "storage_operator", "accepted"),
    "reject": (("requested", "changes_requested"), "storage_operator", "rejected"),
    "request-changes": (("requested",), "storage_operator", "changes_requested"),
    "check-in": (("accepted",), "storage_operator", "checked_in"),
    "release": (("checked_in",), "storage_operator", "released"),
    "cancel": (("requested", "changes_requested", "accepted"), "farmer", "cancelled"),
    "resubmit": (("changes_requested",), "farmer", "requested"),
}


def _facility_change(b: Doc, action: str, from_status: str) -> tuple[Doc, Doc] | None:
    """(extra filter, $inc) applied to the facility for this transition, or None."""
    q = b["qty_kg"]
    if action == "accept":
        fits = {"$lte": [{"$add": ["$reserved_kg", "$occupied_kg", q]}, "$capacity_kg"]}
        return {"status": "active", "$expr": fits}, {"reserved_kg": q}
    if action == "check-in":
        return {"reserved_kg": {"$gte": q}}, {"reserved_kg": -q, "occupied_kg": q}
    if action == "release":
        return {"occupied_kg": {"$gte": q}}, {"occupied_kg": -q}
    if action == "cancel" and from_status == "accepted":
        return {"reserved_kg": {"$gte": q}}, {"reserved_kg": -q}
    return None


async def booking_action(
    db: AsyncDatabase[Doc],
    user: Doc,
    booking_id: ObjectId,
    action: str,
    *,
    note: str | None = None,
    zone_id: str | None = None,
    resubmit: ResubmitIn | None = None,
) -> BookingOut:
    b = await _load_booking(db, user, booking_id)
    allowed_from, actor, target = BOOKING_ACTIONS[action]
    if user["role"] != actor:
        raise AppError(403, "forbidden", "You cannot perform this action on the booking")
    if b["status"] not in allowed_from:
        raise AppError(409, "invalid_transition", f"Booking is {b['status']}")

    extra: Doc = {}
    if action == "check-in" and zone_id:
        zid = parse_object_id(zone_id, "zone")
        if (
            await db.storage_zones.count_documents(
                {"_id": zid, "facility_id": b["facility_id"]}, limit=1
            )
            == 0
        ):
            raise AppError(422, "validation_error", "Zone does not belong to this facility")
        extra["zone_id"] = zid
    if action == "resubmit" and resubmit is not None:
        extra |= {
            "qty_kg": _kg(resubmit.qty, resubmit.unit),
            "display_unit": resubmit.unit,
            "start_date": resubmit.start_date.isoformat(),
            "end_date": resubmit.end_date.isoformat(),
        }
        note = resubmit.note
    by = "farmer" if user["role"] == "farmer" else "storage_operator"
    change = _facility_change(b, action, b["status"])

    async def txn(s: AsyncClientSession) -> tuple[Doc, Doc | None]:
        now = datetime.now(UTC)
        updated = await db.storage_bookings.find_one_and_update(
            {"_id": booking_id, "status": b["status"], "updated_at": b["updated_at"]},
            {
                "$set": {"status": target, "updated_at": now, **extra},
                "$push": {"history": {"status": target, "by": by, "note": note, "at": now}},
            },
            return_document=ReturnDocument.AFTER,
            session=s,
        )
        if updated is None:
            raise AppError(409, "conflict", "This booking changed meanwhile. Reload and try again")
        facility = None
        if change is not None:
            cond, inc = change
            facility = await db.storage_facilities.find_one_and_update(
                {"_id": b["facility_id"], **cond},
                {"$inc": inc, "$set": {"updated_at": now}},
                return_document=ReturnDocument.AFTER,
                session=s,
            )
            if facility is None:
                if action == "accept":
                    raise AppError(
                        409, "insufficient_capacity", "Not enough free capacity for this booking"
                    )
                raise AppError(
                    409, "capacity_mismatch", "Facility capacity records are inconsistent"
                )
        if by == "storage_operator":
            await write_audit(
                db,
                actor_id=user["_id"],
                action=f"booking.{action}",
                target_type="booking",
                target_id=booking_id,
                details={"from": b["status"], "to": target, "qty_kg": b["qty_kg"]}
                | ({"note": note} if note else {}),
                session=s,
            )
        return updated, facility

    updated, facility = await mongo.transaction(txn)
    if facility is not None:
        await hub.broadcast(capacity_message(facility))
    f = facility or await db.storage_facilities.find_one({"_id": b["facility_id"]}) or {}
    await _emit_booking_event(db, updated, action, user, f)
    params = {"commodity": b["commodity"], "qty_kg": updated["qty_kg"], "facility": f.get("name")}
    if by == "storage_operator":
        await notify(db, [b["farmer_id"]], f"booking.{target}", params, FARMER_LINK)
    else:
        params["name"] = user["name"]
        await notify(
            db, await org_member_ids(db, b["org_id"]), f"booking.{target}", params, OPERATOR_LINK
        )
    return (await _booking_views(db, [updated], user))[0]


BOOKING_EVENTS = {"accept": "booking_confirmed", "check-in": "checked_in", "release": "released"}


async def _emit_booking_event(
    db: AsyncDatabase[Doc], booking: Doc, action: str, actor: Doc, facility: Doc
) -> None:
    """Chain storage milestones on the linked batch; custody moves only for whole batches."""
    event = BOOKING_EVENTS.get(action)
    batch_id = booking.get("batch_id")
    if event is None or batch_id is None:
        return
    batch = await db.produce_batches.find_one({"_id": batch_id})
    if batch is None:
        return
    whole = booking["qty_kg"] >= batch["qty_kg"]
    payload: Doc = {
        "booking_id": str(booking["_id"]),
        "facility_id": str(booking["facility_id"]),
        "facility_name": facility.get("name"),
        "district": facility.get("district"),
        "qty_kg": booking["qty_kg"],
        "partial": not whole,
    }
    changes: Doc | None = None
    if whole and event == "checked_in":
        changes = {
            "status": "in_storage",
            "custodian": {
                "type": "facility",
                "id": booking["facility_id"],
                "name": facility.get("name"),
            },
            "location": facility.get("location", batch["location"]),
        }
    if event == "released":
        # Storage conditions over the stay go into the chain before the release itself.
        summary = await freshtrack_service.booking_summary(db, booking)
        if summary is not None:
            await emit(
                db,
                batch_id,
                "observation_summary",
                None,
                {"booking_id": str(booking["_id"]), **summary},
                source="system",
            )
    if whole and event == "released":
        changes = {
            "status": "active",
            "custodian": {"type": "farmer", "id": batch["farmer_id"], "name": None},
        }
    await emit(db, batch_id, event, actor, payload, source="user", batch_changes=changes)
