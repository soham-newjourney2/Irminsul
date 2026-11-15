"""Emergency coordination: simulated flood → exposure → relocation proposals.

No autonomous moves: an authorised human confirms each relocation, which only *requests* a
booking at the target facility (its operator still accepts it through the normal flow).
"""

import json
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.config import REPO_ROOT
from backend.app.core.audit import write_audit
from backend.app.core.errors import AppError
from backend.app.core.geo import GeoPoint, point_out
from backend.app.db.client import Doc
from backend.app.integrations import osrm
from backend.app.integrations.routes import cached_distance
from backend.app.modules.batches.service import emit
from backend.app.modules.notifications.service import notify, org_member_ids
from backend.app.modules.storage import service as storage
from backend.app.modules.storage.schemas import BookingIn

log = logging.getLogger("irminsul.emergency")
SCENARIO_DIR = REPO_ROOT / "data" / "flood_scenarios"
# Irminsul assumption (labelled in the UI): more perishable crops are relocated first.
URGENCY = {"tomato": 1, "potato": 2, "rice": 3, "jute": 3}
CANDIDATES_FOR_ROUTING = 5
LINK = "/emergency.html"


@lru_cache(maxsize=1)
def scenarios() -> dict[str, dict[str, Any]]:
    out = {}
    for path in sorted(SCENARIO_DIR.glob("*.geojson")):
        feature = json.loads(path.read_text(encoding="utf-8"))["features"][0]
        props = feature["properties"]
        out[props["id"]] = {**props, "geometry": feature["geometry"]}
    return out


def _within(geometry: dict[str, Any]) -> Doc:
    return {"location": {"$geoWithin": {"$geometry": geometry}}}


# --- trigger / exposure ---------------------------------------------------------------------


async def trigger(db: AsyncDatabase[Doc], admin: Doc, scenario_id: str) -> Doc:
    sc = scenarios().get(scenario_id)
    if sc is None:
        raise AppError(404, "not_found", "Unknown scenario")
    if await db.emergency_events.count_documents(
        {"scenario_id": scenario_id, "status": "active"}, limit=1
    ):
        raise AppError(409, "already_active", "This scenario is already active")
    now = datetime.now(UTC)
    event: Doc = {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "name": sc["name"],
        "district": sc["district"],
        "geometry": sc["geometry"],
        "note": sc["note"],
        "simulated": True,
        "source": "simulated",
        "is_demo": True,
        "status": "active",
        "triggered_by": admin["_id"],
        "created_at": now,
        "updated_at": now,
    }
    event["_id"] = (await db.emergency_events.insert_one(event)).inserted_id
    exp = await _exposure_docs(db, event)
    plans = 0
    for lot in exp["stored_lots"]:
        await _create_plan(db, event, lot)
        plans += 1
    counts = {k: len(v) for k, v in exp.items()}
    await db.emergency_events.update_one(
        {"_id": event["_id"]}, {"$set": {"exposure_counts": counts, "plans": plans}}
    )
    event |= {"exposure_counts": counts, "plans": plans}
    await write_audit(
        db,
        actor_id=admin["_id"],
        action="demo.flood_trigger",
        target_type="emergency_event",
        target_id=event["_id"],
        details={"scenario_id": scenario_id, **counts},
    )
    params = {"name": sc["name"]}
    await notify(
        db, list({f["farmer_id"] for f in exp["farms"]}), "emergency.farm_exposed", params, LINK
    )
    for org_id in {f["org_id"] for f in exp["facilities"]}:
        await notify(
            db, await org_member_ids(db, org_id), "emergency.facility_exposed", params, LINK
        )
    await notify(
        db,
        list({b["farmer_id"] for b in exp["stored_lots"]}),
        "emergency.stock_exposed",
        params,
        LINK,
    )
    return event


async def _exposure_docs(db: AsyncDatabase[Doc], event: Doc) -> dict[str, list[Doc]]:
    geo = _within(event["geometry"])
    farms = await db.farms.find(geo).to_list(1000)
    facilities = await db.storage_facilities.find(geo).to_list(500)
    fac_ids = [f["_id"] for f in facilities]
    stored = await db.storage_bookings.find(
        {"facility_id": {"$in": fac_ids}, "status": "checked_in"}
    ).to_list(2000)
    upcoming = await db.storage_bookings.find(
        {"facility_id": {"$in": fac_ids}, "status": "accepted"}
    ).to_list(2000)
    return {
        "farms": farms,
        "facilities": facilities,
        "stored_lots": stored,
        "upcoming_bookings": upcoming,
    }


def _point(doc: Doc) -> dict[str, float]:
    p = point_out(doc["location"])
    return {"lat": p.lat, "lng": p.lng}


async def exposure(db: AsyncDatabase[Doc], user: Doc, event_id: ObjectId) -> dict[str, Any]:
    event = await _event(db, event_id)
    exp = await _exposure_docs(db, event)
    role, uid, org = user["role"], user["_id"], user.get("org_id")
    if role == "farmer":
        exp["farms"] = [f for f in exp["farms"] if f["farmer_id"] == uid]
        exp["facilities"] = []
        exp["stored_lots"] = [b for b in exp["stored_lots"] if b["farmer_id"] == uid]
        exp["upcoming_bookings"] = [b for b in exp["upcoming_bookings"] if b["farmer_id"] == uid]
    elif role == "storage_operator":
        exp["farms"] = []
        exp["facilities"] = [f for f in exp["facilities"] if f["org_id"] == org]
        exp["stored_lots"] = [b for b in exp["stored_lots"] if b["org_id"] == org]
        exp["upcoming_bookings"] = [b for b in exp["upcoming_bookings"] if b["org_id"] == org]
    elif role != "admin":
        exp = {k: [] for k in exp}
    facs = {
        f["_id"]: f
        for f in await db.storage_facilities.find(
            {
                "_id": {
                    "$in": list(
                        {b["facility_id"] for b in exp["stored_lots"] + exp["upcoming_bookings"]}
                    )
                }
            }
        ).to_list()
    }
    return {
        "event": event_view(event),
        "farms": [
            {
                "id": str(f["_id"]),
                "name": f["name"],
                "district": f["district"],
                "location": _point(f),
            }
            for f in exp["farms"]
        ],
        "facilities": [
            {
                "id": str(f["_id"]),
                "name": f["name"],
                "district": f["district"],
                "location": _point(f),
                "occupied_kg": f["occupied_kg"],
                "reserved_kg": f["reserved_kg"],
            }
            for f in exp["facilities"]
        ],
        "stored_lots": [_lot_view(b, facs.get(b["facility_id"])) for b in exp["stored_lots"]],
        "upcoming_bookings": [
            _lot_view(b, facs.get(b["facility_id"])) for b in exp["upcoming_bookings"]
        ],
    }


def _lot_view(b: Doc, f: Doc | None) -> dict[str, Any]:
    return {
        "booking_id": str(b["_id"]),
        "batch_id": str(b["batch_id"]) if b.get("batch_id") else None,
        "commodity": b["commodity"],
        "qty_kg": b["qty_kg"],
        "facility": f["name"] if f else None,
        "status": b["status"],
    }


def event_view(e: Doc) -> dict[str, Any]:
    return {
        "id": str(e["_id"]),
        "scenario_id": e["scenario_id"],
        "name": e["name"],
        "district": e["district"],
        "geometry": e["geometry"],
        "note": e["note"],
        "simulated": e["simulated"],
        "status": e["status"],
        "exposure_counts": e.get("exposure_counts", {}),
        "plans": e.get("plans", 0),
        "created_at": e["created_at"],
        "closed_at": e.get("closed_at"),
    }


async def _event(db: AsyncDatabase[Doc], event_id: ObjectId) -> Doc:
    e = await db.emergency_events.find_one({"_id": event_id})
    if e is None:
        raise AppError(404, "not_found", "Emergency event not found")
    return e


async def list_events(db: AsyncDatabase[Doc], limit: int) -> list[dict[str, Any]]:
    rows = (
        await db.emergency_events.find()
        .sort([("status", ASCENDING), ("created_at", DESCENDING)])
        .to_list(limit)
    )
    return [event_view(e) for e in rows]


# --- relocation -------------------------------------------------------------------------------


async def candidate_options(
    db: AsyncDatabase[Doc], geometry: dict[str, Any], origin: Doc, commodity: str, qty_kg: int
) -> list[dict[str, Any]]:
    """Active facilities outside the flood polygon that store the crop and have room now."""
    query: Doc = {
        "_id": {"$ne": origin["_id"]},
        "status": "active",
        "commodities": commodity,
        "$nor": [_within(geometry)],
        "$expr": {
            "$gte": [
                {"$subtract": ["$capacity_kg", {"$add": ["$reserved_kg", "$occupied_kg"]}]},
                qty_kg,
            ]
        },
    }
    rows = await db.storage_facilities.find(query).to_list(200)
    o = point_out(origin["location"])
    rows.sort(
        key=lambda f: osrm.haversine_km(o.lat, o.lng, *reversed(f["location"]["coordinates"]))
    )
    out = []
    for f in rows[:CANDIDATES_FOR_ROUTING]:
        p = point_out(f["location"])
        d = await cached_distance(
            db, GeoPoint(lat=o.lat, lng=o.lng), GeoPoint(lat=p.lat, lng=p.lng)
        )
        free = f["capacity_kg"] - f["reserved_kg"] - f["occupied_kg"]
        out.append(
            {
                "facility_id": str(f["_id"]),
                "name": f["name"],
                "district": f["district"],
                "location": {"lat": p.lat, "lng": p.lng},
                "free_kg": free,
                "capacity_kg": f["capacity_kg"],
                "fit_pct": round(100 * qty_kg / free, 1) if free else None,
                "distance_km": d.km,
                "distance_source": d.source,
                "duration_min": d.duration_min,
            }
        )
    out.sort(key=lambda x: x["distance_km"])
    for rank, opt in enumerate(out, 1):
        opt["rank"] = rank
    return out


async def _create_plan(db: AsyncDatabase[Doc], event: Doc, booking: Doc) -> Doc:
    origin = await db.storage_facilities.find_one({"_id": booking["facility_id"]})
    assert origin is not None  # noqa: S101 — booking references an existing facility
    now = datetime.now(UTC)
    options = await candidate_options(
        db, event["geometry"], origin, booking["commodity"], booking["qty_kg"]
    )
    plan: Doc = {
        "schema_version": 1,
        "event_id": event["_id"],
        "booking_id": booking["_id"],
        "batch_id": booking.get("batch_id"),
        "farmer_id": booking["farmer_id"],
        "from_facility_id": origin["_id"],
        "from_facility_name": origin["name"],
        "from_district": origin["district"],
        "org_id": origin["org_id"],
        "commodity": booking["commodity"],
        "qty_kg": booking["qty_kg"],
        "end_date": booking["end_date"],
        "urgency": URGENCY.get(booking["commodity"], 3),
        "options": options,
        "status": "proposed",
        "simulated": True,
        "is_demo": True,
        "created_at": now,
        "updated_at": now,
    }
    plan["_id"] = (await db.relocation_plans.insert_one(plan)).inserted_id
    return plan


def _plan_view(p: Doc, rate_paise: int | None) -> dict[str, Any]:
    options = []
    for o in p["options"]:
        cost = (
            round(o["distance_km"] * rate_paise * p["qty_kg"] / 100)
            if rate_paise is not None
            else None
        )
        options.append({**o, "cost_paise": cost})
    return {
        "id": str(p["_id"]),
        "event_id": str(p["event_id"]),
        "booking_id": str(p["booking_id"]),
        "batch_id": str(p["batch_id"]) if p.get("batch_id") else None,
        "from_facility": p["from_facility_name"],
        "from_district": p["from_district"],
        "commodity": p["commodity"],
        "qty_kg": p["qty_kg"],
        "urgency": p["urgency"],
        "status": p["status"],
        "options": options,
        "confirmed_facility_id": str(p["confirmed_facility_id"])
        if p.get("confirmed_facility_id")
        else None,
        "new_booking_id": str(p["new_booking_id"]) if p.get("new_booking_id") else None,
        "simulated": p.get("simulated", True),
        "created_at": p["created_at"],
    }


async def list_plans(
    db: AsyncDatabase[Doc], user: Doc, event_id: ObjectId, rate: Decimal | None
) -> list[dict[str, Any]]:
    await _event(db, event_id)
    query: Doc = {"event_id": event_id}
    if user["role"] == "farmer":
        query["farmer_id"] = user["_id"]
    elif user["role"] == "storage_operator":
        query["org_id"] = user.get("org_id")
    elif user["role"] != "admin":
        return []
    rows = (
        await db.relocation_plans.find(query)
        .sort([("urgency", ASCENDING), ("qty_kg", DESCENDING)])
        .to_list(500)
    )
    rate_paise = int(rate * 100) if rate is not None else None
    return [_plan_view(p, rate_paise) for p in rows]


async def confirm(
    db: AsyncDatabase[Doc], user: Doc, plan_id: ObjectId, facility_id: ObjectId
) -> dict[str, Any]:
    plan = await db.relocation_plans.find_one({"_id": plan_id})
    if plan is None or (user["role"] != "admin" and plan["org_id"] != user.get("org_id")):
        raise AppError(404, "not_found", "Relocation plan not found")
    if plan["status"] != "proposed":
        raise AppError(409, "invalid_transition", f"Plan is {plan['status']}")
    event = await _event(db, plan["event_id"])
    if event["status"] != "active":
        raise AppError(409, "event_closed", "This emergency has been closed")
    if str(facility_id) not in {o["facility_id"] for o in plan["options"]}:
        raise AppError(422, "validation_error", "Choose one of the proposed facilities")
    origin = await db.storage_facilities.find_one({"_id": plan["from_facility_id"]})
    assert origin is not None  # noqa: S101
    # Re-check right now: still outside the polygon, crop supported, enough free capacity.
    fresh = await candidate_options(
        db, event["geometry"], origin, plan["commodity"], plan["qty_kg"]
    )
    if str(facility_id) not in {o["facility_id"] for o in fresh}:
        raise AppError(
            409, "insufficient_capacity", "That facility no longer has enough free capacity"
        )
    farmer = await db.users.find_one({"_id": plan["farmer_id"]})
    if farmer is None:
        raise AppError(409, "conflict", "The produce owner's account no longer exists")
    today = datetime.now(UTC).date()
    end = max(date.fromisoformat(plan["end_date"]), today + timedelta(days=1))
    request = BookingIn(
        facility_id=str(facility_id),
        commodity=plan["commodity"],
        qty=Decimal(plan["qty_kg"]),
        unit="kg",
        start_date=today,
        end_date=end,
        batch_id=str(plan["batch_id"]) if plan.get("batch_id") else None,
        note=f"Relocation from {plan['from_facility_name']} — {event['name']}",
    )
    new_booking = await storage.create_booking(db, farmer, request)
    now = datetime.now(UTC)
    updated = await db.relocation_plans.find_one_and_update(
        {"_id": plan_id, "status": "proposed"},
        {
            "$set": {
                "status": "confirmed",
                "confirmed_facility_id": facility_id,
                "new_booking_id": ObjectId(new_booking.id),
                "confirmed_by": user["_id"],
                "confirmed_at": now,
                "updated_at": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise AppError(409, "conflict", "Plan changed meanwhile. Reload and try again")
    target = await db.storage_facilities.find_one({"_id": facility_id})
    await write_audit(
        db,
        actor_id=user["_id"],
        action="relocation.confirm",
        target_type="relocation_plan",
        target_id=plan_id,
        details={
            "event_id": str(event["_id"]),
            "to_facility_id": str(facility_id),
            "new_booking_id": new_booking.id,
            "qty_kg": plan["qty_kg"],
        },
    )
    if plan.get("batch_id"):
        await emit(
            db,
            plan["batch_id"],
            "relocated",
            user,
            {
                "from_facility": plan["from_facility_name"],
                "from_district": plan["from_district"],
                "to_facility": target["name"] if target else None,
                "to_district": target["district"] if target else None,
                "booking_id": new_booking.id,
                "status": "planned",
                "event_id": str(event["_id"]),
                "simulated": True,
            },
            source="user",
        )
    await notify(
        db,
        [plan["farmer_id"]],
        "emergency.relocation_confirmed",
        {"from": plan["from_facility_name"], "to": target["name"] if target else "?"},
        "/farmer/storage.html",
    )
    return _plan_view(updated, None)


async def close(db: AsyncDatabase[Doc], admin: Doc, event_id: ObjectId) -> dict[str, Any]:
    now = datetime.now(UTC)
    e = await db.emergency_events.find_one_and_update(
        {"_id": event_id, "status": "active"},
        {"$set": {"status": "closed", "closed_at": now, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    if e is None:
        raise AppError(409, "invalid_transition", "Event is not active")
    expired = await db.relocation_plans.update_many(
        {"event_id": event_id, "status": "proposed"},
        {"$set": {"status": "expired", "updated_at": now}},
    )
    await write_audit(
        db,
        actor_id=admin["_id"],
        action="demo.flood_close",
        target_type="emergency_event",
        target_id=event_id,
        details={"expired_plans": expired.modified_count},
    )
    return event_view(e)
