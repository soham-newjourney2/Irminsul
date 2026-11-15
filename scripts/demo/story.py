"""Stage demo-story-v1: the Hooghly story (stored potato and tomato, listing, readings)."""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from backend.app.core.reference import Commodity
from backend.app.core.security import hash_password
from backend.app.db.client import Doc
from backend.app.modules.batches import service as batches
from backend.app.modules.batches.schemas import BatchIn
from backend.app.modules.freshtrack import service as freshtrack
from backend.app.modules.listings import service as listings
from backend.app.modules.listings.schemas import ListingIn
from backend.app.modules.storage import service as storage
from backend.app.modules.storage.schemas import BookingIn, ZoneIn
from scripts.demo.accounts import ensure_base, upsert_user

MARKER = "demo-story-v1"
SECOND_FARMER = {
    "email": "farmer2@demo.irminsul.test",
    "name": "Rina Das (demo)",
    "role": "farmer",
    "org": None,
}


async def _mark(db: AsyncDatabase[Doc], collection: str, ids: list) -> None:
    await db[collection].update_many({"_id": {"$in": ids}}, {"$set": {"is_demo": True}})


async def seed(db: AsyncDatabase[Doc], password: str) -> dict[str, int]:
    from bson import ObjectId

    now = datetime.now(UTC)
    today = now.date()
    users = await ensure_base(db, password)
    farmer, op = users["farmer"], users["storage_operator"]
    farmer2 = await upsert_user(db, SECOND_FARMER, await hash_password(password), now)

    farm1 = await db.farms.find_one({"farmer_id": farmer["_id"], "name": "North plot (demo)"})
    farm2 = await db.farms.find_one_and_update(
        {"farmer_id": farmer2["_id"], "name": "Ranaghat plot (demo)"},
        {
            "$setOnInsert": {
                "schema_version": 1,
                "farmer_id": farmer2["_id"],
                "name": "Ranaghat plot (demo)",
                "district": "Nadia",
                "village": "Ranaghat",
                "area_acres": 1.5,
                "location": {"type": "Point", "coordinates": [88.56, 23.17]},
                "is_demo": True,
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
        return_document=True,
    )
    assert farm2 is not None  # noqa: S101 — upserted above
    farm2_id = farm2["_id"]
    assert farm1 is not None  # noqa: S101 — created by ensure_base
    chinsurah = await db.storage_facilities.find_one(
        {"name": "Chinsurah Cold Store (demo)", "org_id": op["org_id"]}
    )
    bardhaman = await db.storage_facilities.find_one(
        {"name": "Bardhaman Cold Store (demo)", "org_id": op["org_id"]}
    )
    assert chinsurah is not None and bardhaman is not None  # noqa: S101

    zone_a = await storage.create_zone(
        db,
        op,
        chinsurah["_id"],
        ZoneIn(
            name="Chamber A — potato", kind="cold", commodity="potato", rule_profile="potato_table"
        ),
    )
    zone_b = await storage.create_zone(
        db,
        op,
        chinsurah["_id"],
        ZoneIn(
            name="Chamber B — tomato", kind="cold", commodity="tomato", rule_profile="tomato_ripe"
        ),
    )
    zone_c = await storage.create_zone(
        db,
        op,
        bardhaman["_id"],
        ZoneIn(
            name="Chamber 1 — potato", kind="cold", commodity="potato", rule_profile="potato_table"
        ),
    )
    await _mark(db, "storage_zones", [ObjectId(z.id) for z in (zone_a, zone_b, zone_c)])

    harvest = today - timedelta(days=12)
    # Story step 3/4: a listed batch the distributor can find and request.
    b_listed = await batches.create(
        db,
        farmer,
        BatchIn(
            farm_id=str(farm1["_id"]),
            commodity="potato",
            variety="Jyoti",
            harvest_date=harvest,
            qty=Decimal(40),
            unit="quintal",
        ),
    )
    lst = await listings.create(
        db,
        farmer,
        ListingIn(
            farm_id=str(farm1["_id"]),
            batch_id=b_listed.id,
            commodity="potato",
            variety="Jyoti",
            qty=Decimal(40),
            unit="quintal",
            harvest_date=harvest,
            available_from=today,
            asking_price_per_quintal=Decimal(1250),
            note="Demo listing",
        ),
    )
    # Story steps 5-7: produce already stored in the cold store inside the Hooghly scenario.
    b_potato = await batches.create(
        db,
        farmer,
        BatchIn(
            farm_id=str(farm1["_id"]),
            commodity="potato",
            variety="Kufri Chandramukhi",
            harvest_date=harvest,
            qty=Decimal(30),
            unit="quintal",
        ),
    )
    b_tomato = await batches.create(
        db,
        farmer2,
        BatchIn(
            farm_id=str(farm2_id),
            commodity="tomato",
            variety="Hybrid",
            harvest_date=today - timedelta(days=2),
            qty=Decimal(8),
            unit="quintal",
        ),
    )
    booking_ids = []
    lots: list[tuple[Doc, Any, Commodity, int, Any]] = [
        (farmer, b_potato, "potato", 30, zone_a),
        (farmer2, b_tomato, "tomato", 8, zone_b),
    ]
    for owner, batch, crop, qty, zone in lots:
        bk = await storage.create_booking(
            db,
            owner,
            BookingIn(
                facility_id=str(chinsurah["_id"]),
                batch_id=batch.id,
                commodity=crop,
                qty=Decimal(qty),
                unit="quintal",
                start_date=today,
                end_date=today + timedelta(days=90),
                note="Demo booking",
            ),
        )
        await storage.booking_action(db, op, ObjectId(bk.id), "accept")
        await storage.booking_action(db, op, ObjectId(bk.id), "check-in", zone_id=zone.id)
        booking_ids.append(ObjectId(bk.id))
    await _mark(db, "storage_bookings", booking_ids)
    await _mark(db, "produce_batches", [ObjectId(b.id) for b in (b_listed, b_potato, b_tomato)])
    await _mark(db, "produce_listings", [ObjectId(lst.id)])

    # Six hours of in-band simulated readings so the FreshTrack charts are not empty.
    rng = random.Random(7)  # noqa: S311 — demo noise
    readings = 0
    for zone, mid_t, mid_rh in ((zone_a, 4.0, 92.5), (zone_b, 14.0, 87.5)):
        ctx = await freshtrack.zone_context(db, ObjectId(zone.id))
        for i in range(36, -1, -1):
            at = now - timedelta(minutes=10 * i)
            await freshtrack.record(
                db,
                ctx,
                at,
                mid_t + rng.gauss(0, 0.12),
                mid_rh + rng.gauss(0, 0.6),
                "simulated",
                None,
                process=False,
            )
            readings += 1
        await freshtrack.process_zone(db, ctx)

    counts = {
        "zones": 3,
        "batches": 3,
        "listings": 1,
        "stored_lots": 2,
        "simulated_readings": readings,
    }
    await db.seed_runs.insert_one({"name": MARKER, "created_at": now, "counts": counts})
    return counts
