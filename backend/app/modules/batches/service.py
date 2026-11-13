"""KrishiChain batches: append-only hash-chained events, corrections, split lineage, QR."""

import logging
import secrets
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from bson import ObjectId
from pymongo import DESCENDING
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from backend.app.core.errors import AppError
from backend.app.core.geo import point_out
from backend.app.core.schemas import parse_object_id
from backend.app.core.units import to_kg
from backend.app.db.client import Doc, mongo
from backend.app.modules.batches.chain import GENESIS_HASH, event_hash, to_ms, verify_chain
from backend.app.modules.batches.schemas import (
    BatchDetailOut,
    BatchIn,
    BatchOut,
    CorrectionIn,
    Custodian,
    EventOut,
    LineageOut,
    PublicBatchOut,
    PublicEventOut,
    SplitIn,
    VerifyOut,
)
from backend.app.modules.farms.service import get_owned as get_owned_farm

log = logging.getLogger("irminsul.batches")

CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O, 1/I
CLOSED_STATUSES = ("split", "delivered")

# Fields shown on the public QR page per event type. Everything else stays private.
PUBLIC_FIELDS: dict[str, tuple[str, ...]] = {
    "created": ("qty_kg", "district", "parent_code"),
    "screened": ("label", "confidence", "model_version"),
    "listed": ("qty_kg",),
    "request_accepted": ("qty_kg",),
    "booking_confirmed": ("qty_kg", "district"),
    "checked_in": ("district",),
    "released": ("district",),
    "observation_summary": ("status",),
    "split": ("children",),
    "dispatched": ("qty_kg",),
    "delivered": ("qty_kg",),
    "relocated": ("from_district", "to_district"),
    "inspection": ("result",),
    "exception": ("kind",),
    "correction": ("ref_seq",),
}


def new_batch_code(now: datetime | None = None) -> str:
    yy = (now or datetime.now(UTC)).strftime("%y")
    return f"IRM-{yy}-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


def _actor(user: Doc | None) -> tuple[ObjectId | None, str | None]:
    return (user["_id"], user["role"]) if user else (None, None)


async def _append(
    db: AsyncDatabase[Doc],
    batch: Doc,
    event_type: str,
    actor: Doc | None,
    payload: dict[str, Any],
    session: AsyncClientSession,
    *,
    source: str = "user",
    event_time: datetime | None = None,
    batch_changes: Doc | None = None,
) -> Doc:
    """Append one event inside the caller's transaction and advance the batch head."""
    now = to_ms(datetime.now(UTC))
    actor_id, actor_role = _actor(actor)
    event: Doc = {
        "schema_version": 1,
        "batch_id": batch["_id"],
        "seq": batch["head_seq"] + 1,
        "type": event_type,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "event_time": to_ms(event_time) if event_time else now,
        "received_at": now,
        "source": source,
        "payload": payload,
        "prev_hash": batch["head_hash"],
    }
    event["hash"] = event_hash(batch["head_hash"], event)
    await db.batch_events.insert_one(event, session=session)
    result = await db.produce_batches.update_one(
        {"_id": batch["_id"], "head_seq": batch["head_seq"]},
        {
            "$set": {
                "head_seq": event["seq"],
                "head_hash": event["hash"],
                "updated_at": now,
                **(batch_changes or {}),
            }
        },
        session=session,
    )
    if result.modified_count != 1:
        raise AppError(409, "conflict", "Batch changed meanwhile. Try again")
    batch.update(head_seq=event["seq"], head_hash=event["hash"], **(batch_changes or {}))
    return event


async def append_event(
    db: AsyncDatabase[Doc],
    batch_id: ObjectId,
    event_type: str,
    actor: Doc | None,
    payload: dict[str, Any],
    *,
    source: str = "user",
    batch_changes: Doc | None = None,
) -> Doc:
    async def txn(s: AsyncClientSession) -> Doc:
        batch = await db.produce_batches.find_one({"_id": batch_id}, session=s)
        if batch is None:
            raise AppError(404, "not_found", "Batch not found")
        return await _append(
            db, batch, event_type, actor, payload, s, source=source, batch_changes=batch_changes
        )

    return await mongo.transaction(txn)


async def emit(
    db: AsyncDatabase[Doc],
    batch_id: ObjectId | None,
    event_type: str,
    actor: Doc | None,
    payload: dict[str, Any],
    *,
    source: str = "system",
    batch_changes: Doc | None = None,
) -> None:
    """Auto-emission from other modules after their own transaction committed. Never raises."""
    if batch_id is None:
        return
    try:
        await append_event(
            db, batch_id, event_type, actor, payload, source=source, batch_changes=batch_changes
        )
    except Exception:
        log.exception("Failed to emit %s for batch %s", event_type, batch_id)


# --- views ------------------------------------------------------------------


def _custodian(batch: Doc) -> Custodian:
    c = batch["custodian"]
    return Custodian(type=c["type"], id=str(c["id"]), name=c.get("name"))


async def _views(db: AsyncDatabase[Doc], rows: list[Doc], viewer: Doc) -> list[BatchOut]:
    ids = [r["_id"] for r in rows]
    links = await db.batch_lineage.find(
        {"$or": [{"parent_id": {"$in": ids}}, {"child_id": {"$in": ids}}]}
    ).to_list()
    other_ids = {lk["parent_id"] for lk in links} | {lk["child_id"] for lk in links}
    codes = {
        b["_id"]: b["batch_code"]
        for b in await db.produce_batches.find(
            {"_id": {"$in": list(other_ids)}}, {"batch_code": 1}
        ).to_list()
    }
    out = []
    for r in rows:
        parent = next((lk for lk in links if lk["child_id"] == r["_id"]), None)
        children = [lk for lk in links if lk["parent_id"] == r["_id"]]
        out.append(
            BatchOut(
                id=str(r["_id"]),
                batch_code=r["batch_code"],
                commodity=r["commodity"],
                variety=r.get("variety"),
                harvest_date=date.fromisoformat(r["harvest_date"]),
                district=r["district"],
                harvest_location=point_out(r["harvest_location"]),
                qty_kg=r["qty_kg"],
                display_unit=r["display_unit"],
                status=r["status"],
                custodian=_custodian(r),
                is_mine=r["farmer_id"] == viewer["_id"],
                is_demo=r.get("is_demo", False),
                parent=(
                    LineageOut(
                        id=str(parent["parent_id"]),
                        batch_code=codes.get(parent["parent_id"], "?"),
                        qty_kg=parent["qty_kg"],
                    )
                    if parent
                    else None
                ),
                children=[
                    LineageOut(
                        id=str(c["child_id"]),
                        batch_code=codes.get(c["child_id"], "?"),
                        qty_kg=c["qty_kg"],
                    )
                    for c in children
                ],
                head_seq=r["head_seq"],
                created_at=r["created_at"],
            )
        )
    return out


def _event_out(ev: Doc) -> EventOut:
    return EventOut(
        seq=ev["seq"],
        type=ev["type"],
        actor_role=ev.get("actor_role"),
        event_time=ev["event_time"],
        received_at=ev["received_at"],
        source=ev["source"],
        payload=ev.get("payload", {}),
        prev_hash=ev["prev_hash"],
        hash=ev["hash"],
    )


async def _events(db: AsyncDatabase[Doc], batch_id: ObjectId) -> list[Doc]:
    return await db.batch_events.find({"batch_id": batch_id}).sort("seq", 1).to_list(None)


# --- create / read ------------------------------------------------------------


def _kg(qty: Decimal, unit: str) -> int:
    try:
        return to_kg(qty, unit)
    except ValueError as exc:
        raise AppError(422, "validation_error", str(exc)) from None


def _new_batch_doc(
    farmer: Doc,
    farm: Doc,
    commodity: str,
    variety: str | None,
    harvest: str,
    qty_kg: int,
    unit: str,
) -> Doc:
    now = to_ms(datetime.now(UTC))
    return {
        "schema_version": 1,
        "batch_code": new_batch_code(now),
        "farmer_id": farmer["_id"],
        "farm_id": farm["_id"],
        "commodity": commodity,
        "variety": variety,
        "harvest_date": harvest,
        "harvest_location": farm["location"],
        "district": farm["district"],
        "location": farm["location"],
        "qty_kg": qty_kg,
        "display_unit": unit,
        "status": "active",
        "custodian": {"type": "farmer", "id": farmer["_id"], "name": farmer["name"]},
        "screening_id": None,
        "head_seq": -1,
        "head_hash": GENESIS_HASH,
        "is_demo": False,
        "created_at": now,
        "updated_at": now,
    }


async def _insert_batch(db: AsyncDatabase[Doc], doc: Doc, session: AsyncClientSession) -> None:
    for _ in range(5):
        try:
            doc["_id"] = (await db.produce_batches.insert_one(doc, session=session)).inserted_id
            return
        except DuplicateKeyError:
            doc["batch_code"] = new_batch_code()
            doc.pop("_id", None)
    raise AppError(500, "internal_error", "Could not allocate a batch code")


async def create(db: AsyncDatabase[Doc], farmer: Doc, data: BatchIn) -> BatchOut:
    farm = await get_owned_farm(db, farmer, parse_object_id(data.farm_id, "farm"))
    if data.harvest_date > datetime.now(UTC).date():
        raise AppError(422, "validation_error", "harvest_date cannot be in the future")
    qty_kg = _kg(data.qty, data.unit)

    async def txn(s: AsyncClientSession) -> Doc:
        doc = _new_batch_doc(
            farmer,
            farm,
            data.commodity,
            data.variety,
            data.harvest_date.isoformat(),
            qty_kg,
            data.unit,
        )
        await _insert_batch(db, doc, s)
        await _append(
            db,
            doc,
            "created",
            farmer,
            {
                "commodity": data.commodity,
                "variety": data.variety,
                "qty_kg": qty_kg,
                "harvest_date": doc["harvest_date"],
                "district": farm["district"],
            },
            s,
        )
        return doc

    doc = await mongo.transaction(txn)
    return (await _views(db, [doc], farmer))[0]


async def list_mine(db: AsyncDatabase[Doc], farmer: Doc, limit: int) -> list[BatchOut]:
    rows = (
        await db.produce_batches.find({"farmer_id": farmer["_id"]})
        .sort("created_at", DESCENDING)
        .to_list(limit)
    )
    return await _views(db, rows, farmer)


async def can_view(db: AsyncDatabase[Doc], user: Doc, batch: Doc) -> bool:
    if user["role"] == "admin" or batch["farmer_id"] == user["_id"]:
        return True
    if user["role"] == "distributor":
        return (
            await db.orders.count_documents(
                {"batch_id": batch["_id"], "distributor_id": user["_id"]}, limit=1
            )
            > 0
        )
    if user["role"] == "storage_operator" and user.get("org_id"):
        return (
            await db.storage_bookings.count_documents(
                {"batch_id": batch["_id"], "org_id": user["org_id"]}, limit=1
            )
            > 0
        )
    return False


async def _visible(db: AsyncDatabase[Doc], user: Doc, batch_id: ObjectId) -> Doc:
    batch = await db.produce_batches.find_one({"_id": batch_id})
    if batch is None or not await can_view(db, user, batch):
        raise AppError(404, "not_found", "Batch not found")
    return batch


async def get_detail(db: AsyncDatabase[Doc], user: Doc, batch_id: ObjectId) -> BatchDetailOut:
    batch = await _visible(db, user, batch_id)
    base = (await _views(db, [batch], user))[0]
    events = [_event_out(e) for e in await _events(db, batch_id)]
    return BatchDetailOut(**base.model_dump(), events=events)


async def _verify(db: AsyncDatabase[Doc], batch: Doc) -> VerifyOut:
    result = verify_chain(await _events(db, batch["_id"]), batch["head_seq"], batch["head_hash"])
    return VerifyOut(
        valid=result.valid,
        events=result.events,
        head_hash=result.head_hash,
        first_invalid_seq=result.first_invalid_seq,
        reason=result.reason,
        checked_at=datetime.now(UTC),
    )


async def verify(db: AsyncDatabase[Doc], user: Doc, batch_id: ObjectId) -> VerifyOut:
    return await _verify(db, await _visible(db, user, batch_id))


async def owned_open_batch(
    db: AsyncDatabase[Doc], farmer: Doc, batch_id: ObjectId, commodity: str
) -> Doc:
    """Validation used by listings/bookings when a batch is linked."""
    batch = await db.produce_batches.find_one({"_id": batch_id, "farmer_id": farmer["_id"]})
    if batch is None:
        raise AppError(404, "not_found", "Batch not found")
    if batch["status"] in CLOSED_STATUSES:
        raise AppError(409, "batch_closed", "This batch is closed (split or delivered)")
    if batch["commodity"] != commodity:
        raise AppError(422, "validation_error", "Batch crop does not match")
    return batch


# --- corrections & split ------------------------------------------------------


async def correct(
    db: AsyncDatabase[Doc], user: Doc, batch_id: ObjectId, seq: int, data: CorrectionIn
) -> BatchDetailOut:
    batch = await _visible(db, user, batch_id)
    original = await db.batch_events.find_one({"batch_id": batch_id, "seq": seq})
    if original is None:
        raise AppError(404, "not_found", "Event not found")
    allowed = (
        user["role"] == "admin"
        or batch["farmer_id"] == user["_id"]
        or original.get("actor_id") == user["_id"]
    )
    if not allowed:
        raise AppError(403, "forbidden", "Only the batch owner or the original actor can correct")
    if original["type"] == "correction":
        raise AppError(422, "validation_error", "Correct the original event, not a correction")
    await append_event(
        db,
        batch_id,
        "correction",
        user,
        {
            "ref_seq": seq,
            "ref_type": original["type"],
            "reason": data.reason,
            "corrected": data.corrected,
        },
    )
    return await get_detail(db, user, batch_id)


async def split(
    db: AsyncDatabase[Doc], farmer: Doc, batch_id: ObjectId, data: SplitIn
) -> BatchDetailOut:
    parts = [_kg(q, data.unit) for q in data.parts]
    parent = await db.produce_batches.find_one({"_id": batch_id, "farmer_id": farmer["_id"]})
    if parent is None:
        raise AppError(404, "not_found", "Batch not found")
    if parent["status"] != "active" or parent["custodian"]["type"] != "farmer":
        raise AppError(
            409, "invalid_transition", "Only active batches held by the farmer can split"
        )
    if sum(parts) > parent["qty_kg"]:
        raise AppError(422, "validation_error", "Parts add up to more than the batch quantity")
    farm = await db.farms.find_one({"_id": parent["farm_id"]})
    if farm is None:
        raise AppError(409, "conflict", "Farm for this batch no longer exists")

    async def txn(s: AsyncClientSession) -> None:
        fresh = await db.produce_batches.find_one({"_id": batch_id}, session=s)
        if fresh is None or fresh["status"] != "active":
            raise AppError(409, "invalid_transition", "Batch changed meanwhile")
        children = []
        for qty in parts:
            child = _new_batch_doc(
                farmer,
                farm,
                fresh["commodity"],
                fresh.get("variety"),
                fresh["harvest_date"],
                qty,
                data.unit,
            )
            await _insert_batch(db, child, s)
            await _append(
                db,
                child,
                "created",
                farmer,
                {
                    "commodity": fresh["commodity"],
                    "variety": fresh.get("variety"),
                    "qty_kg": qty,
                    "harvest_date": fresh["harvest_date"],
                    "district": fresh["district"],
                    "parent_code": fresh["batch_code"],
                },
                s,
            )
            await db.batch_lineage.insert_one(
                {
                    "schema_version": 1,
                    "parent_id": batch_id,
                    "child_id": child["_id"],
                    "qty_kg": qty,
                    "created_at": to_ms(datetime.now(UTC)),
                },
                session=s,
            )
            children.append({"code": child["batch_code"], "qty_kg": qty})
        await _append(
            db,
            fresh,
            "split",
            farmer,
            {"children": children, "remainder_kg": fresh["qty_kg"] - sum(parts)},
            s,
            batch_changes={"status": "split"},
        )

    await mongo.transaction(txn)
    return await get_detail(db, farmer, batch_id)


# --- QR + public view -------------------------------------------------------------


async def qr_token(db: AsyncDatabase[Doc], farmer: Doc, batch_id: ObjectId) -> str:
    batch = await _visible(db, farmer, batch_id)
    if batch["farmer_id"] != farmer["_id"] and farmer["role"] != "admin":
        raise AppError(403, "forbidden", "Only the batch owner can issue a QR code")
    existing = await db.batch_qr_tokens.find_one({"batch_id": batch_id, "revoked": False})
    if existing:
        return existing["token"]
    token = secrets.token_urlsafe(18)
    await db.batch_qr_tokens.insert_one(
        {
            "schema_version": 1,
            "token": token,
            "batch_id": batch_id,
            "revoked": False,
            "created_at": datetime.now(UTC),
        }
    )
    return token


async def public_view(db: AsyncDatabase[Doc], token: str) -> PublicBatchOut:
    row = await db.batch_qr_tokens.find_one({"token": token, "revoked": False})
    batch = await db.produce_batches.find_one({"_id": row["batch_id"]}) if row else None
    if batch is None:
        raise AppError(404, "not_found", "Unknown or revoked code")
    events = await _events(db, batch["_id"])
    public_events = [
        PublicEventOut(
            seq=e["seq"],
            type=e["type"],
            event_time=e["event_time"],
            details={
                k: e["payload"][k]
                for k in PUBLIC_FIELDS.get(e["type"], ())
                if k in e.get("payload", {})
            },
        )
        for e in events
    ]
    return PublicBatchOut(
        batch_code=batch["batch_code"],
        commodity=batch["commodity"],
        variety=batch.get("variety"),
        district=batch["district"],
        harvest_month=batch["harvest_date"][:7],
        qty_kg=batch["qty_kg"],
        status=batch["status"],
        events=public_events,
        chain=await _verify(db, batch),
        is_demo=batch.get("is_demo", False),
    )
