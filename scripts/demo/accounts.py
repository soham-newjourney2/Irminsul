"""Base demo accounts (admin, farmer, distributor, operator) plus one farm and two cold stores."""

from datetime import UTC, datetime

from pymongo.asynchronous.database import AsyncDatabase

from backend.app.core.security import hash_password
from backend.app.db.client import Doc
from backend.app.db.indexes import ensure_indexes

ACCOUNTS = [
    {"email": "admin@demo.irminsul.test", "name": "Demo Admin", "role": "admin", "org": None},
    {
        "email": "farmer@demo.irminsul.test",
        "name": "Gopal Mondal (demo)",
        "role": "farmer",
        "org": None,
    },
    {
        "email": "distributor@demo.irminsul.test",
        "name": "Ria Traders (demo)",
        "role": "distributor",
        "org": "Ria Traders (demo)",
    },
    {
        "email": "operator@demo.irminsul.test",
        "name": "Chinsurah Cold Store (demo)",
        "role": "storage_operator",
        "org": "Chinsurah Cold Store Pvt (demo)",
    },
]


async def upsert_user(db, acc: dict, password_hash: str, now: datetime) -> Doc:
    org_id = None
    if acc["org"]:
        org = await db.organizations.find_one_and_update(
            {"name": acc["org"], "kind": acc["role"]},
            {
                "$set": {"status": "active", "updated_at": now, "is_demo": True},
                "$setOnInsert": {
                    "schema_version": 1,
                    "name": acc["org"],
                    "kind": acc["role"],
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=True,
        )
        org_id = org["_id"]
    user = await db.users.find_one_and_update(
        {"email": acc["email"]},
        {
            "$set": {
                "name": acc["name"],
                "role": acc["role"],
                "status": "active",
                "password_hash": password_hash,
                "org_id": org_id,
                "is_demo": True,
                "updated_at": now,
            },
            "$setOnInsert": {
                "schema_version": 1,
                "email": acc["email"],
                "language": "en",
                "created_at": now,
            },
        },
        upsert=True,
        return_document=True,
    )
    if org_id is not None:
        await db.memberships.update_one(
            {"user_id": user["_id"], "org_id": org_id},
            {"$setOnInsert": {"schema_version": 1, "role": "owner", "created_at": now}},
            upsert=True,
        )
        await db.organizations.update_one({"_id": org_id}, {"$set": {"created_by": user["_id"]}})
    return user


async def ensure_base(db: AsyncDatabase[Doc], password: str) -> dict[str, Doc]:
    """Demo accounts + one farm + two cold stores (inside / outside the Hooghly scenario)."""
    await ensure_indexes(db)
    now = datetime.now(UTC)
    pw_hash = await hash_password(password)
    users = {a["role"]: await upsert_user(db, a, pw_hash, now) for a in ACCOUNTS}
    farmer = users["farmer"]
    await db.farms.update_one(
        {"farmer_id": farmer["_id"], "name": "North plot (demo)"},
        {
            "$setOnInsert": {
                "schema_version": 1,
                "farmer_id": farmer["_id"],
                "name": "North plot (demo)",
                "district": "Hooghly",
                "village": "Pandua",
                "area_acres": 2.5,
                "location": {"type": "Point", "coordinates": [88.28, 23.08]},
                "is_demo": True,
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    op = users["storage_operator"]
    await db.storage_facilities.update_one(
        {"org_id": op["org_id"], "name": "Chinsurah Cold Store (demo)"},
        {
            "$setOnInsert": {
                "schema_version": 1,
                "org_id": op["org_id"],
                "name": "Chinsurah Cold Store (demo)",
                "district": "Hooghly",
                "address": "Demo address, Chinsurah",
                "location": {"type": "Point", "coordinates": [88.40, 22.88]},
                "commodities": ["potato", "tomato"],
                "capacity_kg": 50000,
                "reserved_kg": 0,
                "occupied_kg": 0,
                "status": "active",
                "contact_email": op["email"],
                "created_by": op["_id"],
                "is_demo": True,
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    await db.storage_facilities.update_one(
        {"org_id": op["org_id"], "name": "Bardhaman Cold Store (demo)"},
        {
            "$setOnInsert": {
                "schema_version": 1,
                "org_id": op["org_id"],
                "name": "Bardhaman Cold Store (demo)",
                "district": "Purba Bardhaman",
                "address": "Demo address, Bardhaman",
                "location": {"type": "Point", "coordinates": [87.86, 23.24]},
                "commodities": ["potato", "tomato"],
                "capacity_kg": 80000,
                "reserved_kg": 0,
                "occupied_kg": 0,
                "status": "active",
                "contact_email": op["email"],
                "created_by": op["_id"],
                "is_demo": True,
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return users
