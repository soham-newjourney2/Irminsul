"""Create local demo accounts (+ one demo farm and cold store) for manual testing.

Usage: uv run python -I scripts/demo_accounts.py
Password: SEED_DEMO_PASSWORD from .env (never hard-coded). If unset, a random password is
generated and printed once. Everything created here is marked is_demo: true.
Full demo seeding (planning §5 story) is scripts/seed.py in M7.
"""

import asyncio
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import get_settings
from backend.app.core.security import hash_password
from backend.app.db.client import Doc, mongo
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


async def main() -> int:
    settings = get_settings()
    await mongo.connect(settings)
    if mongo.db is None:
        print("MONGODB_URI not set", file=sys.stderr)
        return 1
    db = mongo.db
    secret = settings.seed_demo_password
    generated = secret is None
    password = secrets.token_urlsafe(9) if secret is None else secret.get_secret_value()
    if len(password) < 8:
        print("SEED_DEMO_PASSWORD must be at least 8 characters", file=sys.stderr)
        return 1
    try:
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
        print("Demo accounts ready:")
        for a in ACCOUNTS:
            print(f"  {a['role']:<17} {a['email']}")
        if generated:
            print(
                "Password (generated, shown once; set SEED_DEMO_PASSWORD in .env to choose):",
                password,
            )
        else:
            print("Password: the SEED_DEMO_PASSWORD value from your .env")
    finally:
        await mongo.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
