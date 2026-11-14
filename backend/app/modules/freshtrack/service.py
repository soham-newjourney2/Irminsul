"""FreshTrack: observations, alert lifecycle, stale checks, notifications, batch events."""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.core.audit import write_audit
from backend.app.core.errors import AppError
from backend.app.core.schemas import parse_object_id
from backend.app.db.client import Doc
from backend.app.modules.batches.service import emit
from backend.app.modules.freshtrack import engine, rules
from backend.app.modules.freshtrack.engine import Finding, Reading
from backend.app.modules.freshtrack.schemas import AlertOut, ObservationIn, ObservationOut
from backend.app.modules.notifications.service import notify, org_member_ids

log = logging.getLogger("irminsul.freshtrack")
RANK = {"info": 0, "warning": 1, "critical": 2}
EXCURSION_KINDS = ("temp_high", "temp_low", "rh_high", "rh_low")
OPERATOR_LINK = "/storage/freshtrack.html"
FARMER_LINK = "/farmer/storage.html"
LIVE = {"superseded": {"$ne": True}}


# --- context & access ------------------------------------------------------------------


async def zone_context(db: AsyncDatabase[Doc], zone_id: ObjectId) -> dict[str, Any]:
    zone = await db.storage_zones.find_one({"_id": zone_id})
    if zone is None:
        raise AppError(404, "not_found", "Zone not found")
    facility = await db.storage_facilities.find_one({"_id": zone["facility_id"]})
    if facility is None:
        raise AppError(404, "not_found", "Facility not found")
    commodity = zone.get("commodity") or (
        facility["commodities"][0] if len(facility["commodities"]) == 1 else None
    )
    return {
        "zone": zone,
        "facility": facility,
        "commodity": commodity,
        "profile": rules.profile_for(commodity, zone.get("rule_profile")),
    }


async def _operator_ctx(db: AsyncDatabase[Doc], user: Doc, zone_id: ObjectId) -> dict[str, Any]:
    ctx = await zone_context(db, zone_id)
    if user["role"] == "admin":
        return ctx
    if user["role"] != "storage_operator" or ctx["facility"]["org_id"] != user.get("org_id"):
        raise AppError(404, "not_found", "Zone not found")
    return ctx


async def affected(
    db: AsyncDatabase[Doc], ctx: dict[str, Any]
) -> tuple[list[ObjectId], list[ObjectId]]:
    """Farmers and batches with produce checked in to this zone (or facility, if no zone set)."""
    rows = await db.storage_bookings.find(
        {
            "status": "checked_in",
            "facility_id": ctx["facility"]["_id"],
            "$or": [{"zone_id": ctx["zone"]["_id"]}, {"zone_id": None}],
        },
        {"farmer_id": 1, "batch_id": 1},
    ).to_list(500)
    farmers = list(dict.fromkeys(r["farmer_id"] for r in rows))
    batches = list(dict.fromkeys(r["batch_id"] for r in rows if r.get("batch_id")))
    return farmers, batches


# --- observations ------------------------------------------------------------------------


def _obs_out(o: Doc) -> ObservationOut:
    return ObservationOut(
        id=str(o["_id"]),
        zone_id=str(o["zone_id"]),
        observed_at=o["observed_at"],
        temp_c=o.get("temp_c"),
        rh_pct=o.get("rh_pct"),
        source=o["source"],
        note=o.get("note"),
    )


async def record(
    db: AsyncDatabase[Doc],
    ctx: dict[str, Any],
    observed_at: datetime,
    temp_c: float | None,
    rh_pct: float | None,
    source: str,
    actor_id: ObjectId | None,
    note: str | None = None,
    process: bool = True,
) -> tuple[Doc, list[Doc]]:
    doc: Doc = {
        "schema_version": 1,
        "zone_id": ctx["zone"]["_id"],
        "facility_id": ctx["facility"]["_id"],
        "org_id": ctx["facility"]["org_id"],
        "observed_at": observed_at,
        "temp_c": round(temp_c, 2) if temp_c is not None else None,
        "rh_pct": round(rh_pct, 1) if rh_pct is not None else None,
        "source": source,
        "note": note,
        "created_by": actor_id,
        "created_at": datetime.now(UTC),
        "is_demo": source == "simulated",
    }
    doc["_id"] = (await db.storage_observations.insert_one(doc)).inserted_id
    alerts = await process_zone(db, ctx) if process else []
    return doc, alerts


async def add_observation(
    db: AsyncDatabase[Doc], user: Doc, data: ObservationIn
) -> tuple[ObservationOut, list[AlertOut]]:
    ctx = await _operator_ctx(db, user, parse_object_id(data.zone_id, "zone"))
    if data.temp is None and data.rh_pct is None:
        raise AppError(422, "validation_error", "Give a temperature, a humidity, or both")
    now = datetime.now(UTC)
    at = data.observed_at or now
    at = at if at.tzinfo else at.replace(tzinfo=UTC)
    if at > now + timedelta(minutes=5):
        raise AppError(422, "validation_error", "Reading time is in the future")
    if at < now - timedelta(days=7):
        raise AppError(422, "validation_error", "Reading is older than 7 days")
    temp_c = None
    if data.temp is not None:
        temp_c = (data.temp - 32) * 5 / 9 if data.temp_unit == "F" else data.temp
        if not -40 <= temp_c <= 70:
            raise AppError(
                422, "validation_error", "Temperature is physically impossible for a store"
            )
    doc, alerts = await record(db, ctx, at, temp_c, data.rh_pct, "manual", user["_id"], data.note)
    return _obs_out(doc), await alert_views(db, alerts)


async def _readings(db: AsyncDatabase[Doc], zone_id: ObjectId, since: datetime) -> list[Doc]:
    return (
        await db.storage_observations.find(
            {"zone_id": zone_id, "observed_at": {"$gte": since}, **LIVE}
        )
        .sort("observed_at", ASCENDING)
        .to_list(2000)
    )


def _as_readings(rows: list[Doc]) -> list[Reading]:
    return [
        Reading(
            observed_at=r["observed_at"]
            if r["observed_at"].tzinfo
            else r["observed_at"].replace(tzinfo=UTC),
            temp_c=r.get("temp_c"),
            rh_pct=r.get("rh_pct"),
        )
        for r in rows
    ]


async def list_observations(
    db: AsyncDatabase[Doc], user: Doc, zone_id: ObjectId, hours: int
) -> dict[str, Any]:
    ctx = await zone_context(db, zone_id)
    if user["role"] == "farmer":
        farmers, _ = await affected(db, ctx)
        if user["_id"] not in farmers:
            raise AppError(404, "not_found", "Zone not found")
    elif user["role"] != "admin" and ctx["facility"]["org_id"] != user.get("org_id"):
        raise AppError(404, "not_found", "Zone not found")
    rows = await _readings(db, zone_id, datetime.now(UTC) - timedelta(hours=hours))
    last = await db.storage_observations.find_one(
        {"zone_id": zone_id, **LIVE}, sort=[("observed_at", DESCENDING)]
    )
    return {
        "zone": {
            "id": str(ctx["zone"]["_id"]),
            "name": ctx["zone"]["name"],
            "facility_id": str(ctx["facility"]["_id"]),
            "facility_name": ctx["facility"]["name"],
            "commodity": ctx["commodity"],
        },
        "profile": ctx["profile"],
        "readings": [_obs_out(r) for r in rows],
        "last_reading_at": last["observed_at"] if last else None,
    }


# --- alert engine glue ----------------------------------------------------------------------


async def process_zone(
    db: AsyncDatabase[Doc], ctx: dict[str, Any], simulated: bool = False
) -> list[Doc]:
    zone_id = ctx["zone"]["_id"]
    rows = await _readings(db, zone_id, datetime.now(UTC) - timedelta(hours=48))
    if not rows:
        return []
    simulated = simulated or rows[-1]["source"] == "simulated"
    findings = engine.evaluate(_as_readings(rows), ctx["profile"], rules.defaults())
    changed = [await upsert_alert(db, ctx, f, simulated) for f in findings]
    found = {f.kind for f in findings}
    latest_at = rows[-1]["observed_at"]
    # Conditions no longer present: keep the alert open (a human resolves it), mark it cleared.
    await db.storage_alerts.update_many(
        {
            "zone_id": zone_id,
            "status": {"$ne": "resolved"},
            "condition_active": True,
            "kind": {"$nin": list(found)},
        },
        {
            "$set": {
                "condition_active": False,
                "cleared_at": latest_at,
                "updated_at": datetime.now(UTC),
            }
        },
    )
    return changed


async def upsert_alert(
    db: AsyncDatabase[Doc], ctx: dict[str, Any], f: Finding, simulated: bool
) -> Doc:
    now = datetime.now(UTC)
    farmers, batches = await affected(db, ctx)
    existing = await db.storage_alerts.find_one(
        {"zone_id": ctx["zone"]["_id"], "kind": f.kind, "status": {"$ne": "resolved"}}
    )
    profile = ctx["profile"]
    profile_view = (
        {
            "id": profile["id"],
            "label": profile["label"],
            "temp_min_c": profile.get("temp_min_c"),
            "temp_max_c": profile.get("temp_max_c"),
            "rh_min": profile.get("rh_min"),
            "rh_max": profile.get("rh_max"),
            "verified": profile["verified"],
            "source": {
                "org": profile["source"]["org"],
                "url": profile["source"]["url"],
                "pages": profile["source"].get("pages"),
            },
        }
        if profile
        else None
    )
    if existing:
        escalated = RANK[f.severity] > RANK[existing["severity"]]
        update: Doc = {
            "$set": {
                "severity": f.severity if escalated else existing["severity"],
                "latest_at": f.latest_at,
                "duration_min": f.duration_min,
                "peak": f.peak,
                "condition_active": True,
                "cleared_at": None,
                "details": f.details,
                "affected_farmer_ids": farmers,
                "affected_batch_ids": batches,
                "updated_at": now,
            }
        }
        if escalated:
            update["$push"] = {
                "history": {"action": "escalated", "to": f.severity, "by": None, "at": now}
            }
        doc = await db.storage_alerts.find_one_and_update(
            {"_id": existing["_id"]}, update, return_document=ReturnDocument.AFTER
        )
        assert doc is not None  # noqa: S101 — just updated by id
        if escalated:
            await _notify(db, ctx, doc, "freshtrack.alert_escalated")
        return doc
    doc = {
        "schema_version": 1,
        "facility_id": ctx["facility"]["_id"],
        "org_id": ctx["facility"]["org_id"],
        "zone_id": ctx["zone"]["_id"],
        "facility_name": ctx["facility"]["name"],
        "zone_name": ctx["zone"]["name"],
        "kind": f.kind,
        "severity": f.severity,
        "status": "open",
        "metric": f.metric,
        "threshold": f.threshold,
        "peak": f.peak,
        "started_at": f.started_at,
        "latest_at": f.latest_at,
        "duration_min": f.duration_min,
        "condition_active": True,
        "cleared_at": None,
        "profile": profile_view,
        "details": f.details,
        "simulated": simulated,
        "affected_farmer_ids": farmers,
        "affected_batch_ids": batches,
        "history": [{"action": "opened", "severity": f.severity, "by": None, "at": now}],
        "inspection_id": None,
        "is_demo": simulated,
        "created_at": now,
        "updated_at": now,
    }
    doc["_id"] = (await db.storage_alerts.insert_one(doc)).inserted_id
    await _notify(db, ctx, doc, "freshtrack.alert_opened")
    if f.severity in ("warning", "critical"):
        for bid in batches:
            await emit(
                db,
                bid,
                "exception",
                None,
                {
                    "alert_id": str(doc["_id"]),
                    "kind": f.kind,
                    "severity": f.severity,
                    "facility_name": ctx["facility"]["name"],
                    "district": ctx["facility"]["district"],
                    "threshold": f.threshold,
                    "peak": f.peak,
                    "simulated": simulated,
                },
                source="simulator" if simulated else "system",
            )
    return doc


async def _notify(db: AsyncDatabase[Doc], ctx: dict[str, Any], alert: Doc, kind: str) -> None:
    params = {
        "kind": alert["kind"],
        "severity": alert["severity"],
        "facility": ctx["facility"]["name"],
        "zone": ctx["zone"]["name"],
    }
    await notify(
        db, await org_member_ids(db, ctx["facility"]["org_id"]), kind, params, OPERATOR_LINK
    )
    if alert["kind"] != "unusual":  # info-only statistics are for the operator
        await notify(db, alert.get("affected_farmer_ids", []), kind, params, FARMER_LINK)


async def check_stale(
    db: AsyncDatabase[Doc], now: datetime | None = None, simulated: bool = False
) -> int:
    """Background task + admin demo trigger. `now` may be advanced for a labelled what-if run."""
    now = now or datetime.now(UTC)
    d = rules.defaults()
    pipeline: list[Doc] = [
        {"$match": {"observed_at": {"$gte": now - timedelta(days=7)}, **LIVE}},
        {"$group": {"_id": "$zone_id", "last": {"$max": "$observed_at"}}},
    ]
    count = 0
    for row in await (await db.storage_observations.aggregate(pipeline)).to_list():
        last = row["last"] if row["last"].tzinfo else row["last"].replace(tzinfo=UTC)
        f = engine.stale(last, now, d)
        if f is None:
            continue
        try:
            ctx = await zone_context(db, row["_id"])
        except AppError:
            continue
        await upsert_alert(db, ctx, f, simulated)
        count += 1
    return count


# --- lifecycle ---------------------------------------------------------------------------------


async def alert_views(db: AsyncDatabase[Doc], rows: list[Doc]) -> list[AlertOut]:
    ids = [r["inspection_id"] for r in rows if r.get("inspection_id")]
    insp = {i["_id"]: i for i in await db.inspection_records.find({"_id": {"$in": ids}}).to_list()}
    out = []
    for r in rows:
        i = insp.get(r.get("inspection_id"))
        out.append(
            AlertOut(
                id=str(r["_id"]),
                facility_id=str(r["facility_id"]),
                facility_name=r.get("facility_name"),
                zone_id=str(r["zone_id"]),
                zone_name=r.get("zone_name"),
                kind=r["kind"],
                severity=r["severity"],
                status=r["status"],
                metric=r.get("metric"),
                threshold=r.get("threshold"),
                peak=r.get("peak"),
                started_at=r["started_at"],
                latest_at=r["latest_at"],
                duration_min=r["duration_min"],
                condition_active=r["condition_active"],
                cleared_at=r.get("cleared_at"),
                profile=r.get("profile"),
                details=r.get("details", {}),
                simulated=r.get("simulated", False),
                history=[
                    {k: (str(v) if isinstance(v, ObjectId) else v) for k, v in h.items()}
                    for h in r.get("history", [])
                ],
                inspection=(
                    {
                        "findings": i["findings"],
                        "corrective_action": i["corrective_action"],
                        "inspected_at": i["inspected_at"],
                    }
                    if i
                    else None
                ),
                created_at=r["created_at"],
            )
        )
    return out


async def list_alerts(
    db: AsyncDatabase[Doc], user: Doc, status: str | None, zone_id: ObjectId | None, limit: int
) -> list[AlertOut]:
    if user["role"] == "farmer":
        query: Doc = {"affected_farmer_ids": user["_id"], "kind": {"$ne": "unusual"}}
    elif user["role"] == "storage_operator":
        if user.get("org_id") is None:
            return []
        query = {"org_id": user["org_id"]}
    elif user["role"] == "admin":
        query = {}
    else:
        raise AppError(403, "forbidden", "You do not have access to storage alerts")
    if status:
        query["status"] = status
    if zone_id:
        query["zone_id"] = zone_id
    rows = (
        await db.storage_alerts.find(query)
        .sort([("status", ASCENDING), ("updated_at", DESCENDING)])
        .to_list(limit)
    )
    return await alert_views(db, rows)


async def _owned_alert(db: AsyncDatabase[Doc], user: Doc, alert_id: ObjectId) -> Doc:
    a = await db.storage_alerts.find_one({"_id": alert_id})
    if a is None or (user["role"] != "admin" and a["org_id"] != user.get("org_id")):
        raise AppError(404, "not_found", "Alert not found")
    return a


async def acknowledge(
    db: AsyncDatabase[Doc], user: Doc, alert_id: ObjectId, note: str | None
) -> AlertOut:
    a = await _owned_alert(db, user, alert_id)
    now = datetime.now(UTC)
    doc = await db.storage_alerts.find_one_and_update(
        {"_id": alert_id, "status": "open"},
        {
            "$set": {
                "status": "acknowledged",
                "acknowledged_by": user["_id"],
                "acknowledged_at": now,
                "updated_at": now,
            },
            "$push": {
                "history": {"action": "acknowledged", "by": user["_id"], "note": note, "at": now}
            },
        },
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise AppError(409, "invalid_transition", f"Alert is {a['status']}")
    await write_audit(
        db,
        actor_id=user["_id"],
        action="alert.acknowledge",
        target_type="storage_alert",
        target_id=alert_id,
        details={"kind": a["kind"]},
    )
    return (await alert_views(db, [doc]))[0]


async def resolve(
    db: AsyncDatabase[Doc],
    user: Doc,
    alert_id: ObjectId,
    findings: str,
    corrective_action: str,
    inspected_at: datetime | None,
) -> AlertOut:
    a = await _owned_alert(db, user, alert_id)
    if a["status"] == "resolved":
        raise AppError(409, "invalid_transition", "Alert is already resolved")
    if a["condition_active"]:
        raise AppError(
            409,
            "condition_active",
            "The condition is still present. Fix it and record a normal reading first",
        )
    now = datetime.now(UTC)
    insp: Doc = {
        "schema_version": 1,
        "alert_id": alert_id,
        "zone_id": a["zone_id"],
        "facility_id": a["facility_id"],
        "org_id": a["org_id"],
        "findings": findings.strip(),
        "corrective_action": corrective_action.strip(),
        "inspected_at": inspected_at or now,
        "inspected_by": user["_id"],
        "created_at": now,
    }
    insp["_id"] = (await db.inspection_records.insert_one(insp)).inserted_id
    doc = await db.storage_alerts.find_one_and_update(
        {"_id": alert_id, "status": {"$in": ["open", "acknowledged"]}},
        {
            "$set": {
                "status": "resolved",
                "resolved_by": user["_id"],
                "resolved_at": now,
                "inspection_id": insp["_id"],
                "updated_at": now,
            },
            "$push": {"history": {"action": "resolved", "by": user["_id"], "at": now}},
        },
        return_document=ReturnDocument.AFTER,
    )
    if doc is None:
        raise AppError(409, "conflict", "Alert changed meanwhile. Reload and try again")
    await write_audit(
        db,
        actor_id=user["_id"],
        action="alert.resolve",
        target_type="storage_alert",
        target_id=alert_id,
        details={"kind": a["kind"], "inspection_id": str(insp["_id"])},
    )
    ctx = await zone_context(db, a["zone_id"])
    await _notify(db, ctx, doc, "freshtrack.alert_resolved")
    for bid in a.get("affected_batch_ids", []):
        await emit(
            db,
            bid,
            "inspection",
            user,
            {
                "alert_id": str(alert_id),
                "kind": a["kind"],
                "result": "resolved",
                "corrective_action": insp["corrective_action"],
            },
            source="user",
        )
    return (await alert_views(db, [doc]))[0]


async def booking_summary(db: AsyncDatabase[Doc], booking: Doc) -> dict[str, Any] | None:
    """Storage conditions over a booking's stay (used for the batch 'observation_summary' event)."""
    zone_id = booking.get("zone_id")
    if zone_id is None:
        return None
    start = next(
        (h["at"] for h in booking.get("history", []) if h.get("status") == "checked_in"), None
    )
    if start is None:
        return None
    rows = (
        await db.storage_observations.find(
            {"zone_id": zone_id, "observed_at": {"$gte": start}, **LIVE}
        )
        .sort("observed_at", ASCENDING)
        .to_list(5000)
    )
    ctx = await zone_context(db, zone_id)
    alerts = await db.storage_alerts.count_documents(
        {"zone_id": zone_id, "kind": {"$in": list(EXCURSION_KINDS)}, "started_at": {"$gte": start}}
    )
    return {
        **engine.summarise(_as_readings(rows), ctx["profile"]),
        "excursion_alerts": alerts,
        "profile_id": ctx["profile"]["id"] if ctx["profile"] else None,
    }
