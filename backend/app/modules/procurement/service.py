"""Purchase requests (offer/counter) and orders. Acceptance runs in a transaction."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from bson import ObjectId
from pymongo import DESCENDING, ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.core.audit import write_audit
from backend.app.core.errors import AppError
from backend.app.core.units import rupees_to_paise, to_kg, total_paise
from backend.app.db.client import Doc, mongo
from backend.app.modules.batches.service import emit
from backend.app.modules.listings.schemas import OPEN_FOR_REQUESTS
from backend.app.modules.listings.service import refresh_status
from backend.app.modules.notifications.service import notify
from backend.app.modules.procurement.schemas import (
    CounterIn,
    OrderOut,
    PurchaseRequestIn,
    PurchaseRequestOut,
)
from backend.app.modules.users.service import parties, party_out

Side = Literal["farmer", "distributor"]
OPEN_REQUEST = ("pending", "countered")
FARMER_LINK = "/farmer/sell.html"
DISTRIBUTOR_LINK = "/distributor/deals.html"


def _side(user: Doc, doc: Doc) -> Side | None:
    if doc["farmer_id"] == user["_id"]:
        return "farmer"
    if doc["distributor_id"] == user["_id"]:
        return "distributor"
    return None


def _awaiting(status: str) -> Side | None:
    if status == "pending":
        return "farmer"
    if status == "countered":
        return "distributor"
    return None


def _qty_kg(qty: Decimal, unit: str) -> int:
    try:
        return to_kg(qty, unit)
    except ValueError as exc:
        raise AppError(422, "validation_error", str(exc)) from None


# --- views ------------------------------------------------------------------


async def _request_views(
    db: AsyncDatabase[Doc], rows: list[Doc], viewer: Doc
) -> list[PurchaseRequestOut]:
    listing_ids = list({r["listing_id"] for r in rows})
    listings = {
        x["_id"]: x for x in await db.produce_listings.find({"_id": {"$in": listing_ids}}).to_list()
    }
    people = await parties(db, [r["farmer_id"] for r in rows] + [r["distributor_id"] for r in rows])
    out: list[PurchaseRequestOut] = []
    for r in rows:
        lst = listings.get(r["listing_id"], {})
        viewer_is_farmer = r["farmer_id"] == viewer["_id"]
        other = r["distributor_id"] if viewer_is_farmer else r["farmer_id"]
        out.append(
            PurchaseRequestOut(
                id=str(r["_id"]),
                listing_id=str(r["listing_id"]),
                commodity=r["commodity"],
                variety=lst.get("variety"),
                district=lst.get("district", ""),
                qty_kg=r["qty_kg"],
                display_unit=r["display_unit"],
                offered_price_paise_per_quintal=r["price_paise_per_quintal"],
                asking_price_paise_per_quintal=lst.get("asking_price_paise_per_quintal", 0),
                delivery_mode=r["delivery_mode"],
                needed_by=date.fromisoformat(r["needed_by"]) if r.get("needed_by") else None,
                note=r.get("note"),
                status=r["status"],
                awaiting=_awaiting(r["status"]),
                history=r.get("history", []),
                counterparty=party_out(
                    people.get(other),
                    reveal=r["status"] == "accepted",
                    district=None if viewer_is_farmer else lst.get("district"),
                ),
                order_id=str(r["order_id"]) if r.get("order_id") else None,
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
        )
    return out


async def _order_views(db: AsyncDatabase[Doc], rows: list[Doc]) -> list[OrderOut]:
    people = await parties(db, [r["farmer_id"] for r in rows] + [r["distributor_id"] for r in rows])
    return [
        OrderOut(
            id=str(r["_id"]),
            listing_id=str(r["listing_id"]),
            request_id=str(r["request_id"]),
            batch_id=str(r["batch_id"]) if r.get("batch_id") else None,
            commodity=r["commodity"],
            variety=r.get("variety"),
            district=r["district"],
            qty_kg=r["qty_kg"],
            display_unit=r["display_unit"],
            agreed_price_paise_per_quintal=r["price_paise_per_quintal"],
            total_paise=r["total_paise"],
            delivery_mode=r["delivery_mode"],
            status=r["status"],
            history=r.get("history", []),
            # An order exists only after acceptance → contact reveal is allowed for both sides.
            farmer=party_out(people.get(r["farmer_id"]), reveal=True, district=r["district"]),
            distributor=party_out(people.get(r["distributor_id"]), reveal=True),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


# --- purchase requests ------------------------------------------------------


async def create_request(
    db: AsyncDatabase[Doc], distributor: Doc, data: PurchaseRequestIn, listing_id: ObjectId
) -> PurchaseRequestOut:
    listing = await db.produce_listings.find_one({"_id": listing_id})
    if listing is None or listing["status"] == "draft":
        raise AppError(404, "not_found", "Listing not found")
    if listing["status"] not in OPEN_FOR_REQUESTS:
        raise AppError(409, "listing_unavailable", "This listing is not accepting requests")
    qty_kg = _qty_kg(data.qty, data.unit)
    if qty_kg > listing["remaining_kg"]:
        raise AppError(409, "insufficient_quantity", "Requested quantity exceeds what is available")
    price = rupees_to_paise(data.price_per_quintal)
    now = datetime.now(UTC)
    doc: Doc = {
        "schema_version": 1,
        "listing_id": listing_id,
        "farmer_id": listing["farmer_id"],
        "distributor_id": distributor["_id"],
        "commodity": listing["commodity"],
        "qty_kg": qty_kg,
        "display_unit": data.unit,
        "price_paise_per_quintal": price,
        "delivery_mode": data.delivery_mode,
        "needed_by": data.needed_by.isoformat() if data.needed_by else None,
        "note": data.note,
        "status": "pending",
        "history": [
            {
                "by": "distributor",
                "action": "offer",
                "qty_kg": qty_kg,
                "price_paise_per_quintal": price,
                "note": data.note,
                "at": now,
            }
        ],
        "order_id": None,
        "is_demo": False,
        "created_at": now,
        "updated_at": now,
    }
    doc["_id"] = (await db.purchase_requests.insert_one(doc)).inserted_id
    await notify(
        db,
        [listing["farmer_id"]],
        "request.created",
        {"name": distributor["name"], "commodity": listing["commodity"], "qty_kg": qty_kg},
        FARMER_LINK,
    )
    return (await _request_views(db, [doc], distributor))[0]


async def list_requests(
    db: AsyncDatabase[Doc], user: Doc, status: str | None, limit: int
) -> list[PurchaseRequestOut]:
    field = "farmer_id" if user["role"] == "farmer" else "distributor_id"
    query: Doc = {field: user["_id"]}
    if status:
        query["status"] = status
    rows = await db.purchase_requests.find(query).sort("updated_at", DESCENDING).to_list(limit)
    return await _request_views(db, rows, user)


async def _load_request(
    db: AsyncDatabase[Doc], user: Doc, request_id: ObjectId
) -> tuple[Doc, Side]:
    doc = await db.purchase_requests.find_one({"_id": request_id})
    side = _side(user, doc) if doc else None
    if doc is None or side is None:
        raise AppError(404, "not_found", "Purchase request not found")
    return doc, side


async def get_request(
    db: AsyncDatabase[Doc], user: Doc, request_id: ObjectId
) -> PurchaseRequestOut:
    doc, _ = await _load_request(db, user, request_id)
    return (await _request_views(db, [doc], user))[0]


def _require_turn(doc: Doc, side: Side) -> None:
    if doc["status"] not in OPEN_REQUEST:
        raise AppError(409, "invalid_transition", "This request is already closed")
    if _awaiting(doc["status"]) != side:
        raise AppError(409, "not_your_turn", "Waiting for the other party to respond")


async def _transition(
    db: AsyncDatabase[Doc],
    doc: Doc,
    side: Side,
    new_status: str,
    action: str,
    *,
    extra: Doc | None = None,
    note: str | None = None,
    session: AsyncClientSession | None = None,
) -> Doc:
    now = datetime.now(UTC)
    entry: Doc = {"by": side, "action": action, "note": note, "at": now}
    if extra:
        entry |= {
            "qty_kg": extra.get("qty_kg"),
            "price_paise_per_quintal": extra.get("price_paise_per_quintal"),
        }
    updated = await db.purchase_requests.find_one_and_update(
        {"_id": doc["_id"], "status": doc["status"], "updated_at": doc["updated_at"]},
        {
            "$set": {"status": new_status, "updated_at": now, **(extra or {})},
            "$push": {"history": entry},
        },
        return_document=ReturnDocument.AFTER,
        session=session,
    )
    if updated is None:
        raise AppError(409, "conflict", "This request changed meanwhile. Reload and try again")
    return updated


async def counter(
    db: AsyncDatabase[Doc], user: Doc, request_id: ObjectId, data: CounterIn
) -> PurchaseRequestOut:
    doc, side = await _load_request(db, user, request_id)
    _require_turn(doc, side)
    unit = data.unit or doc["display_unit"]
    qty_kg = _qty_kg(data.qty, unit) if data.qty is not None else doc["qty_kg"]
    listing = await db.produce_listings.find_one({"_id": doc["listing_id"]})
    if listing is None or listing["status"] not in OPEN_FOR_REQUESTS:
        raise AppError(409, "listing_unavailable", "This listing is not accepting requests")
    if qty_kg > listing["remaining_kg"]:
        raise AppError(409, "insufficient_quantity", "Quantity exceeds what is available")
    extra = {
        "qty_kg": qty_kg,
        "display_unit": unit,
        "price_paise_per_quintal": rupees_to_paise(data.price_per_quintal),
    }
    new_status = "countered" if side == "farmer" else "pending"
    updated = await _transition(db, doc, side, new_status, "counter", extra=extra, note=data.note)
    other = doc["distributor_id"] if side == "farmer" else doc["farmer_id"]
    await notify(
        db,
        [other],
        "request.countered",
        {"name": user["name"], "commodity": doc["commodity"]},
        DISTRIBUTOR_LINK if side == "farmer" else FARMER_LINK,
    )
    return (await _request_views(db, [updated], user))[0]


async def reject(
    db: AsyncDatabase[Doc], user: Doc, request_id: ObjectId, note: str | None
) -> PurchaseRequestOut:
    doc, side = await _load_request(db, user, request_id)
    if side != "farmer":
        raise AppError(403, "forbidden", "Only the farmer can reject; distributors withdraw")
    _require_turn(doc, side)
    updated = await _transition(db, doc, side, "rejected", "reject", note=note)
    await notify(
        db,
        [doc["distributor_id"]],
        "request.rejected",
        {"commodity": doc["commodity"]},
        DISTRIBUTOR_LINK,
    )
    return (await _request_views(db, [updated], user))[0]


async def withdraw(
    db: AsyncDatabase[Doc], user: Doc, request_id: ObjectId, note: str | None
) -> PurchaseRequestOut:
    doc, side = await _load_request(db, user, request_id)
    if side != "distributor":
        raise AppError(403, "forbidden", "Only the distributor can withdraw a request")
    if doc["status"] not in OPEN_REQUEST:
        raise AppError(409, "invalid_transition", "This request is already closed")
    updated = await _transition(db, doc, side, "withdrawn", "withdraw", note=note)
    await notify(
        db, [doc["farmer_id"]], "request.withdrawn", {"commodity": doc["commodity"]}, FARMER_LINK
    )
    return (await _request_views(db, [updated], user))[0]


async def accept(db: AsyncDatabase[Doc], user: Doc, request_id: ObjectId) -> OrderOut:
    """Accept current terms → order. One transaction: request, listing decrement, order."""
    doc, side = await _load_request(db, user, request_id)
    _require_turn(doc, side)
    qty_kg = doc["qty_kg"]

    async def txn(s: AsyncClientSession) -> Doc:
        req = await _transition(db, doc, side, "accepted", "accept", session=s)
        listing = await db.produce_listings.find_one_and_update(
            {
                "_id": doc["listing_id"],
                "status": {"$in": list(OPEN_FOR_REQUESTS)},
                "remaining_kg": {"$gte": qty_kg},
            },
            {"$inc": {"remaining_kg": -qty_kg}, "$set": {"updated_at": datetime.now(UTC)}},
            return_document=ReturnDocument.AFTER,
            session=s,
        )
        if listing is None:
            raise AppError(409, "insufficient_quantity", "Not enough quantity left on this listing")
        now = datetime.now(UTC)
        order: Doc = {
            "schema_version": 1,
            "listing_id": doc["listing_id"],
            "request_id": doc["_id"],
            "batch_id": listing.get("batch_id"),
            "farmer_id": doc["farmer_id"],
            "distributor_id": doc["distributor_id"],
            "commodity": doc["commodity"],
            "variety": listing.get("variety"),
            "district": listing["district"],
            "qty_kg": qty_kg,
            "display_unit": req["display_unit"],
            "price_paise_per_quintal": req["price_paise_per_quintal"],
            "total_paise": total_paise(qty_kg, req["price_paise_per_quintal"]),
            "currency": "INR",
            "delivery_mode": req["delivery_mode"],
            "status": "confirmed",
            "history": [{"status": "confirmed", "by": side, "note": None, "at": now}],
            "is_demo": False,
            "created_at": now,
            "updated_at": now,
        }
        order["_id"] = (await db.orders.insert_one(order, session=s)).inserted_id
        await db.purchase_requests.update_one(
            {"_id": doc["_id"]}, {"$set": {"order_id": order["_id"]}}, session=s
        )
        await refresh_status(db, doc["listing_id"], session=s)
        await write_audit(
            db,
            actor_id=user["_id"],
            action="order.create",
            target_type="order",
            target_id=order["_id"],
            details={"request_id": str(doc["_id"]), "qty_kg": qty_kg},
            session=s,
        )
        return order

    order = await mongo.transaction(txn)
    await emit(
        db,
        order.get("batch_id"),
        "request_accepted",
        user,
        {"order_id": str(order["_id"]), "request_id": str(doc["_id"]), "qty_kg": qty_kg},
        source="user",
    )
    other = doc["distributor_id"] if side == "farmer" else doc["farmer_id"]
    await notify(
        db,
        [other],
        "request.accepted",
        {"name": user["name"], "commodity": doc["commodity"], "qty_kg": qty_kg},
        DISTRIBUTOR_LINK if side == "farmer" else FARMER_LINK,
    )
    return (await _order_views(db, [order]))[0]


# --- orders -----------------------------------------------------------------

# (from, to) → who may do it
ORDER_TRANSITIONS: dict[str, tuple[tuple[str, ...], frozenset[str]]] = {
    "dispatch": (("confirmed",), frozenset({"farmer"})),
    "deliver": (("dispatched",), frozenset({"distributor"})),
    "close": (("delivered",), frozenset({"farmer", "distributor"})),
    "cancel": (("confirmed",), frozenset({"farmer", "distributor"})),
}
ADMIN_CANCELLABLE = ("confirmed", "dispatched")
TARGET = {
    "dispatch": "dispatched",
    "deliver": "delivered",
    "close": "closed",
    "cancel": "cancelled",
}


async def list_orders(
    db: AsyncDatabase[Doc], user: Doc, status: str | None, limit: int
) -> list[OrderOut]:
    query: Doc = {}
    if user["role"] == "farmer":
        query["farmer_id"] = user["_id"]
    elif user["role"] == "distributor":
        query["distributor_id"] = user["_id"]
    if status:
        query["status"] = status
    rows = await db.orders.find(query).sort("updated_at", DESCENDING).to_list(limit)
    return await _order_views(db, rows)


async def _load_order(db: AsyncDatabase[Doc], user: Doc, order_id: ObjectId) -> tuple[Doc, str]:
    doc = await db.orders.find_one({"_id": order_id})
    if doc is None:
        raise AppError(404, "not_found", "Order not found")
    if user["role"] == "admin":
        return doc, "admin"
    side = _side(user, doc)
    if side is None:
        raise AppError(404, "not_found", "Order not found")
    return doc, side


async def get_order(db: AsyncDatabase[Doc], user: Doc, order_id: ObjectId) -> OrderOut:
    doc, _ = await _load_order(db, user, order_id)
    return (await _order_views(db, [doc]))[0]


async def order_action(
    db: AsyncDatabase[Doc], user: Doc, order_id: ObjectId, action: str, note: str | None
) -> OrderOut:
    doc, side = await _load_order(db, user, order_id)
    allowed_from, actors = ORDER_TRANSITIONS[action]
    if side == "admin" and action == "cancel":
        allowed_from = ADMIN_CANCELLABLE
    elif side not in actors:
        raise AppError(403, "forbidden", "You cannot perform this action on the order")
    if doc["status"] not in allowed_from:
        raise AppError(409, "invalid_transition", f"Order is {doc['status']}")
    target = TARGET[action]

    async def txn(s: AsyncClientSession) -> Doc:
        now = datetime.now(UTC)
        updated = await db.orders.find_one_and_update(
            {"_id": order_id, "status": doc["status"]},
            {
                "$set": {"status": target, "updated_at": now},
                "$push": {"history": {"status": target, "by": side, "note": note, "at": now}},
            },
            return_document=ReturnDocument.AFTER,
            session=s,
        )
        if updated is None:
            raise AppError(409, "conflict", "This order changed meanwhile. Reload and try again")
        if target == "cancelled":
            await db.produce_listings.update_one(
                {"_id": doc["listing_id"]},
                {"$inc": {"remaining_kg": doc["qty_kg"]}, "$set": {"updated_at": now}},
                session=s,
            )
        await refresh_status(db, doc["listing_id"], session=s)
        await write_audit(
            db,
            actor_id=user["_id"],
            action=f"order.{action}",
            target_type="order",
            target_id=order_id,
            details={"from": doc["status"], "to": target} | ({"note": note} if note else {}),
            session=s,
        )
        return updated

    updated = await mongo.transaction(txn)
    await _emit_order_event(db, doc, target, user)
    params = {"commodity": doc["commodity"], "qty_kg": doc["qty_kg"]}
    for uid, role, link in (
        (doc["farmer_id"], "farmer", FARMER_LINK),
        (doc["distributor_id"], "distributor", DISTRIBUTOR_LINK),
    ):
        if role != side:
            await notify(db, [uid], f"order.{target}", params, link)
    return (await _order_views(db, [updated]))[0]


async def _emit_order_event(db: AsyncDatabase[Doc], order: Doc, target: str, actor: Doc) -> None:
    """Chain dispatch/delivery on the linked batch. Custody moves only for whole-batch orders."""
    batch_id = order.get("batch_id")
    if batch_id is None or target not in ("dispatched", "delivered"):
        return
    batch = await db.produce_batches.find_one({"_id": batch_id}, {"qty_kg": 1})
    whole = batch is not None and order["qty_kg"] >= batch["qty_kg"]
    changes: Doc | None = None
    if whole and target == "dispatched":
        changes = {"status": "in_transit"}
    elif whole and target == "delivered":
        entry = (await parties(db, [order["distributor_id"]])).get(order["distributor_id"])
        name = (entry[1] or {}).get("name") or entry[0].get("name") if entry else None
        changes = {
            "status": "delivered",
            "custodian": {"type": "distributor", "id": order["distributor_id"], "name": name},
        }
    await emit(
        db,
        batch_id,
        target,
        actor,
        {"order_id": str(order["_id"]), "qty_kg": order["qty_kg"], "partial": not whole},
        source="user",
        batch_changes=changes,
    )
