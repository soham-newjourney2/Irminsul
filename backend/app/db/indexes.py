"""Index definitions (planning §7). Each milestone adds indexes for its own collections."""

from pymongo import ASCENDING, DESCENDING, GEOSPHERE, IndexModel
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.db.client import Doc

INDEXES: dict[str, list[IndexModel]] = {
    # Identity (M1)
    "users": [
        IndexModel([("phone", ASCENDING)], unique=True, name="phone_unique"),
        IndexModel([("status", ASCENDING), ("created_at", DESCENDING)], name="status_created"),
    ],
    "organizations": [IndexModel([("status", ASCENDING)], name="status")],
    "memberships": [
        IndexModel([("user_id", ASCENDING), ("org_id", ASCENDING)], unique=True, name="user_org"),
        IndexModel([("org_id", ASCENDING)], name="org"),
    ],
    # Platform
    "audit_logs": [IndexModel([("created_at", ASCENDING)], name="created_at")],
    "idempotency_keys": [
        IndexModel([("key", ASCENDING), ("user_id", ASCENDING)], unique=True, name="key_user"),
        IndexModel([("created_at", ASCENDING)], expireAfterSeconds=24 * 3600, name="ttl_24h"),
    ],
    # Market / storage (M2) — geo indexes needed for proximity search
    "farms": [IndexModel([("location", GEOSPHERE)], name="location_2dsphere")],
    "produce_listings": [
        IndexModel([("status", ASCENDING), ("commodity", ASCENDING)], name="status_commodity"),
        IndexModel([("location", GEOSPHERE)], name="location_2dsphere"),
    ],
    "storage_facilities": [IndexModel([("location", GEOSPHERE)], name="location_2dsphere")],
}


async def ensure_indexes(db: AsyncDatabase[Doc]) -> None:
    for collection, models in INDEXES.items():
        await db[collection].create_indexes(models)
