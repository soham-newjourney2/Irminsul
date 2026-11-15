"""Stage demo-story-v2: more farmers, crops, deals, bookings and a FreshTrack alert.

Runs after demo-story-v1 from scripts/seed.py. Everything is fictional, built through the real
services and marked is_demo. Mandi prices, weather and routes stay real and are not seeded.
"""

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.core.errors import AppError
from backend.app.core.geo import GeoPoint
from backend.app.core.security import hash_password
from backend.app.db.client import Doc
from backend.app.modules.batches import service as batches
from backend.app.modules.batches.schemas import BatchIn, SplitIn
from backend.app.modules.emergency import service as emergency
from backend.app.modules.farms import service as farms
from backend.app.modules.farms.schemas import FarmIn
from backend.app.modules.freshtrack import service as freshtrack
from backend.app.modules.listings import service as listings
from backend.app.modules.listings.schemas import ListingIn
from backend.app.modules.procurement import service as procurement
from backend.app.modules.procurement.schemas import CounterIn, PurchaseRequestIn
from backend.app.modules.storage import service as storage
from backend.app.modules.storage.schemas import BookingIn, FacilityIn, ZoneIn
from scripts.demo.accounts import upsert_user

MARKER = "demo-story-v2"

PEOPLE = [
    {
        "email": "farmer3@demo.irminsul.test",
        "name": "Sukumar Pal (demo)",
        "role": "farmer",
        "org": None,
    },
    {
        "email": "farmer4@demo.irminsul.test",
        "name": "Anwara Khatun (demo)",
        "role": "farmer",
        "org": None,
    },
    {
        "email": "farmer5@demo.irminsul.test",
        "name": "Biswajit Mahato (demo)",
        "role": "farmer",
        "org": None,
    },
    {
        "email": "distributor2@demo.irminsul.test",
        "name": "Arup Bose (demo)",
        "role": "distributor",
        "org": "Bose Agro Traders (demo)",
    },
    {
        "email": "operator2@demo.irminsul.test",
        "name": "Kakoli Sen (demo)",
        "role": "storage_operator",
        "org": "Ganga Cold Chain Pvt (demo)",
    },
]

DEMO_COLLECTIONS = (
    "farms",
    "storage_facilities",
    "storage_zones",
    "storage_bookings",
    "produce_batches",
    "produce_listings",
    "purchase_requests",
    "orders",
)


def q(n: float) -> Decimal:
    return Decimal(str(n))


async def seed_more(db: AsyncDatabase[Doc], password: str) -> dict[str, int]:
    now = datetime.now(UTC)
    today = now.date()
    pw_hash = await hash_password(password)
    made: dict[str, list[ObjectId]] = {c: [] for c in DEMO_COLLECTIONS}

    users = {p["email"].split("@")[0]: await upsert_user(db, p, pw_hash, now) for p in PEOPLE}
    sukumar, anwara, biswajit = users["farmer3"], users["farmer4"], users["farmer5"]
    bose, kakoli = users["distributor2"], users["operator2"]
    gopal = await db.users.find_one({"email": "farmer@demo.irminsul.test"})
    ria = await db.users.find_one({"email": "distributor@demo.irminsul.test"})
    gopal_op = await db.users.find_one({"email": "operator@demo.irminsul.test"})
    admin = await db.users.find_one({"email": "admin@demo.irminsul.test"})
    assert gopal and ria and gopal_op and admin  # noqa: S101 — created by demo-story-v1

    async def farm(
        owner: Doc, name: str, district: str, village: str, acres: float, lat: float, lng: float
    ) -> str:
        out = await farms.create(
            db,
            owner,
            FarmIn(
                name=name,
                district=district,
                village=village,
                area_acres=q(acres),
                location=GeoPoint(lat=lat, lng=lng),
            ),
        )
        made["farms"].append(ObjectId(out.id))
        return out.id

    async def batch(
        owner: Doc, farm_id: str, crop: Any, variety: str, qty: float, days_ago: int
    ) -> str:
        out = await batches.create(
            db,
            owner,
            BatchIn(
                farm_id=farm_id,
                commodity=crop,
                variety=variety,
                harvest_date=today - timedelta(days=days_ago),
                qty=q(qty),
                unit="quintal",
            ),
        )
        made["produce_batches"].append(ObjectId(out.id))
        return out.id

    async def listing(
        owner: Doc,
        farm_id: str,
        batch_id: str,
        crop: Any,
        variety: str,
        qty: float,
        price: int,
        days_ago: int,
        note: str,
    ) -> str:
        out = await listings.create(
            db,
            owner,
            ListingIn(
                farm_id=farm_id,
                batch_id=batch_id,
                commodity=crop,
                variety=variety,
                qty=q(qty),
                unit="quintal",
                harvest_date=today - timedelta(days=days_ago),
                available_from=today,
                asking_price_per_quintal=q(price),
                note=note,
            ),
        )
        made["produce_listings"].append(ObjectId(out.id))
        return out.id

    async def booking(
        owner: Doc, facility_id: str, batch_id: str, crop: Any, qty: float, days: int
    ) -> ObjectId:
        out = await storage.create_booking(
            db,
            owner,
            BookingIn(
                facility_id=facility_id,
                batch_id=batch_id,
                commodity=crop,
                qty=q(qty),
                unit="quintal",
                start_date=today,
                end_date=today + timedelta(days=days),
                note="Demo booking",
            ),
        )
        made["storage_bookings"].append(ObjectId(out.id))
        return ObjectId(out.id)

    async def request(buyer: Doc, listing_id: str, qty: float, price: int, note: str) -> ObjectId:
        out = await procurement.create_request(
            db,
            buyer,
            PurchaseRequestIn(
                listing_id=listing_id,
                qty=q(qty),
                unit="quintal",
                price_per_quintal=q(price),
                note=note,
            ),
            ObjectId(listing_id),
        )
        made["purchase_requests"].append(ObjectId(out.id))
        return ObjectId(out.id)

    memari = await farm(
        sukumar, "Memari fields (demo)", "Purba Bardhaman", "Memari", 4.2, 23.17, 88.11
    )
    beldanga = await farm(
        anwara, "Beldanga plot (demo)", "Murshidabad", "Beldanga", 2.8, 23.93, 88.25
    )
    arambagh = await farm(
        biswajit, "Arambagh farm (demo)", "Hooghly", "Arambagh", 3.1, 22.88, 87.78
    )

    async def facility(
        name: str,
        district: str,
        address: str,
        lat: float,
        lng: float,
        crops: list[Any],
        tonnes: int,
    ) -> str:
        out = await storage.create_facility(
            db,
            kakoli,
            FacilityIn(
                name=name,
                district=district,
                address=address,
                location=GeoPoint(lat=lat, lng=lng),
                commodities=crops,
                capacity=q(tonnes),
                capacity_unit="tonne",
                contact_email=kakoli["email"],
            ),
        )
        made["storage_facilities"].append(ObjectId(out.id))
        return out.id

    async def zone(facility_id: str, name: str, kind: Any, crop: Any, profile: str) -> str:
        out = await storage.create_zone(
            db,
            kakoli,
            ObjectId(facility_id),
            ZoneIn(name=name, kind=kind, commodity=crop, rule_profile=profile),
        )
        made["storage_zones"].append(ObjectId(out.id))
        return out.id

    manikchak = await facility(
        "Manikchak Cold Store (demo)",
        "Malda",
        "Demo address, Manikchak",
        24.90,
        88.0,
        ["potato", "tomato"],
        60,
    )
    jiaganj = await facility(
        "Jiaganj Jute Godown (demo)",
        "Murshidabad",
        "Demo address, Jiaganj",
        24.24,
        88.27,
        ["jute", "rice"],
        120,
    )
    m1 = await zone(manikchak, "Chamber M1 — potato", "cold", "potato", "potato_table")
    m2 = await zone(manikchak, "Chamber M2 — tomato", "cold", "tomato", "tomato_ripe")
    g1 = await zone(jiaganj, "Godown 1 — jute bales", "ambient", "jute", "jute_bales")

    bardhaman = await db.storage_facilities.find_one({"name": "Bardhaman Cold Store (demo)"})
    chinsurah = await db.storage_facilities.find_one({"name": "Chinsurah Cold Store (demo)"})
    bardhaman_zone = (
        await db.storage_zones.find_one(
            {"name": "Chamber 1 — potato", "facility_id": bardhaman["_id"]}
        )
        if bardhaman
        else None
    )
    gopal_listing = await db.produce_listings.find_one(
        {"farmer_id": gopal["_id"], "status": {"$in": ["active", "partially_fulfilled"]}}
    )
    assert bardhaman and chinsurah and bardhaman_zone  # noqa: S101

    rice = await batch(sukumar, memari, "rice", "Swarna", 60, 18)
    rice_listing = await listing(
        sukumar, memari, rice, "rice", "Swarna", 60, 2300, 18, "Sun-dried, bagged"
    )
    potato_b = await batch(sukumar, memari, "potato", "Kufri Jyoti", 40, 10)
    bk = await booking(sukumar, str(bardhaman["_id"]), potato_b, "potato", 40, 120)
    await storage.booking_action(db, gopal_op, bk, "accept")
    await storage.booking_action(db, gopal_op, bk, "check-in", zone_id=str(bardhaman_zone["_id"]))

    jute_sale = await batch(anwara, beldanga, "jute", "JRO-204", 25, 25)
    jute_listing = await listing(
        anwara, beldanga, jute_sale, "jute", "JRO-204", 25, 5200, 25, "Retted and graded"
    )
    jute_store = await batch(anwara, beldanga, "jute", "JRO-204", 30, 25)
    bk = await booking(anwara, jiaganj, jute_store, "jute", 30, 60)
    await storage.booking_action(db, kakoli, bk, "accept")
    await storage.booking_action(db, kakoli, bk, "check-in", zone_id=g1)

    tomato = await batch(biswajit, arambagh, "tomato", "Hybrid", 18, 1)
    await batches.split(
        db, biswajit, ObjectId(tomato), SplitIn(parts=[q(12), q(6)], unit="quintal")
    )
    kids = {}
    async for link in db.batch_lineage.find({"parent_id": ObjectId(tomato)}):
        child = await db.produce_batches.find_one({"_id": link["child_id"]})
        if child:
            kids[child["qty_kg"]] = str(child["_id"])
            made["produce_batches"].append(child["_id"])
    tomato_listing = await listing(
        biswajit, arambagh, kids[1200], "tomato", "Hybrid", 12, 1800, 1, "Firm, ripening"
    )
    bk = await booking(biswajit, manikchak, kids[600], "tomato", 6, 30)
    await storage.booking_action(db, kakoli, bk, "accept")
    pukhraj = await batch(biswajit, arambagh, "potato", "Kufri Pukhraj", 35, 6)
    await booking(biswajit, str(chinsurah["_id"]), pukhraj, "potato", 35, 90)

    r = await request(ria, rice_listing, 30, 2250, "Can collect from Memari")
    order = await procurement.accept(db, sukumar, r)
    await procurement.order_action(db, sukumar, ObjectId(order.id), "dispatch", "Loaded on truck")
    await procurement.order_action(
        db, ria, ObjectId(order.id), "deliver", "Received in good condition"
    )
    made["orders"].append(ObjectId(order.id))

    r = await request(ria, tomato_listing, 6, 1750, "For Sealdah market")
    order = await procurement.accept(db, biswajit, r)
    made["orders"].append(ObjectId(order.id))

    await request(bose, jute_listing, 10, 4950, "Need by next week")
    if gopal_listing:
        r = await request(bose, str(gopal_listing["_id"]), 20, 1180, "Repeat buyer")
        await procurement.counter(
            db, gopal, r, CounterIn(price_per_quintal=q(1230), note="Best I can do")
        )

    rng = random.Random(11)  # noqa: S311 — demo noise
    readings = 0
    plans = [
        (
            str(bardhaman_zone["_id"]),
            lambda i: (
                4.0 + rng.gauss(0, 0.1) if i > 6 else 4.7 + (6 - i) * 0.26 + rng.gauss(0, 0.04)
            ),
            lambda i: 93 + rng.gauss(0, 0.6),
        ),
        (m1, lambda i: 3.9 + rng.gauss(0, 0.12), lambda i: 92 + rng.gauss(0, 0.6)),
        (m2, lambda i: 14.1 + rng.gauss(0, 0.12), lambda i: 87 + rng.gauss(0, 0.6)),
        (
            g1,
            lambda i: 27.5 + 1.2 * math.sin(i / 6) + rng.gauss(0, 0.2),
            lambda i: 60 + rng.gauss(0, 1.2),
        ),
    ]
    for zone_id, temp, rh in plans:
        ctx = await freshtrack.zone_context(db, ObjectId(zone_id))
        for i in range(36, -1, -1):
            await freshtrack.record(
                db,
                ctx,
                now - timedelta(minutes=10 * i),
                round(temp(i), 2),
                round(rh(i), 1),
                "simulated",
                None,
                process=False,
            )
            readings += 1
        await freshtrack.process_zone(db, ctx)

    flood = 0
    try:
        event = await emergency.trigger(db, admin, "ganga_murshidabad_malda")
        await db.emergency_events.update_one({"_id": event["_id"]}, {"$set": {"is_demo": True}})
        flood = 1
    except AppError as err:
        if err.status_code != 409:
            raise

    for coll, ids in made.items():
        if ids:
            await db[coll].update_many({"_id": {"$in": ids}}, {"$set": {"is_demo": True}})

    counts = {k: len(v) for k, v in made.items()} | {
        "accounts": len(PEOPLE),
        "simulated_readings": readings,
        "flood_drills": flood,
    }
    await db.seed_runs.insert_one({"name": MARKER, "created_at": now, "counts": counts})
    return counts
