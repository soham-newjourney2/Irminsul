"""Index definitions. Each milestone adds indexes for its own collections."""

from pymongo import ASCENDING, DESCENDING, GEOSPHERE, IndexModel
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.db.client import Doc

INDEXES: dict[str, list[IndexModel]] = {
    # Identity (M1)
    "users": [
        # Partial: accounts created before the email switch have no email and are ignored.
        IndexModel(
            [("email", ASCENDING)],
            unique=True,
            name="email_unique",
            partialFilterExpression={"email": {"$type": "string"}},
        ),
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
    # Market (M2)
    "farms": [
        IndexModel([("location", GEOSPHERE)], name="location_2dsphere"),
        IndexModel([("farmer_id", ASCENDING)], name="farmer"),
    ],
    "produce_listings": [
        IndexModel([("status", ASCENDING), ("commodity", ASCENDING)], name="status_commodity"),
        IndexModel([("location", GEOSPHERE)], name="location_2dsphere"),
        IndexModel([("farmer_id", ASCENDING), ("created_at", DESCENDING)], name="farmer_created"),
    ],
    "purchase_requests": [
        IndexModel([("farmer_id", ASCENDING), ("updated_at", DESCENDING)], name="farmer_updated"),
        IndexModel(
            [("distributor_id", ASCENDING), ("updated_at", DESCENDING)], name="distributor_updated"
        ),
        IndexModel([("listing_id", ASCENDING), ("status", ASCENDING)], name="listing_status"),
    ],
    "orders": [
        IndexModel([("farmer_id", ASCENDING), ("updated_at", DESCENDING)], name="farmer_updated"),
        IndexModel(
            [("distributor_id", ASCENDING), ("updated_at", DESCENDING)], name="distributor_updated"
        ),
        IndexModel([("listing_id", ASCENDING), ("status", ASCENDING)], name="listing_status"),
    ],
    # Storage (M2)
    "storage_facilities": [
        IndexModel([("location", GEOSPHERE)], name="location_2dsphere"),
        IndexModel([("org_id", ASCENDING)], name="org"),
    ],
    "storage_zones": [IndexModel([("facility_id", ASCENDING)], name="facility")],
    "storage_bookings": [
        IndexModel([("farmer_id", ASCENDING), ("updated_at", DESCENDING)], name="farmer_updated"),
        IndexModel([("org_id", ASCENDING), ("updated_at", DESCENDING)], name="org_updated"),
    ],
    # KrishiChain (M3)
    "produce_batches": [
        IndexModel([("batch_code", ASCENDING)], unique=True, name="batch_code_unique"),
        IndexModel([("farmer_id", ASCENDING), ("created_at", DESCENDING)], name="farmer_created"),
    ],
    "batch_events": [
        IndexModel([("batch_id", ASCENDING), ("seq", ASCENDING)], unique=True, name="batch_seq")
    ],
    "batch_lineage": [
        IndexModel([("parent_id", ASCENDING)], name="parent"),
        IndexModel([("child_id", ASCENDING)], name="child"),
    ],
    "batch_qr_tokens": [
        IndexModel([("token", ASCENDING)], unique=True, name="token_unique"),
        IndexModel([("batch_id", ASCENDING)], name="batch"),
    ],
    # Farmer intelligence (M4)
    "crop_screenings": [
        IndexModel([("farmer_id", ASCENDING), ("created_at", DESCENDING)], name="farmer_created")
    ],
    "weather_cache": [
        IndexModel([("key", ASCENDING)], unique=True, name="key_unique"),
        IndexModel([("fetched_at", ASCENDING)], expireAfterSeconds=6 * 3600, name="ttl_6h"),
    ],
    "price_observations": [
        IndexModel(
            [
                ("source", ASCENDING),
                ("market_key", ASCENDING),
                ("commodity", ASCENDING),
                ("variety", ASCENDING),
                ("grade", ASCENDING),
                ("arrival_date", ASCENDING),
            ],
            unique=True,
            name="obs_unique",
        ),
        IndexModel([("crop", ASCENDING), ("arrival_date", DESCENDING)], name="crop_date"),
        IndexModel([("arrival_date", DESCENDING)], name="arrival_date"),
        IndexModel(
            [("crop", ASCENDING), ("market_key", ASCENDING), ("arrival_date", DESCENDING)],
            name="crop_market_date",
        ),
    ],
    "markets": [
        IndexModel([("key", ASCENDING)], unique=True, name="key_unique"),
        IndexModel([("location", GEOSPHERE)], name="location_2dsphere"),
    ],
    "route_cache": [IndexModel([("key", ASCENDING)], unique=True, name="key_unique")],
    # FreshTrack (M5)
    "storage_observations": [
        IndexModel([("zone_id", ASCENDING), ("observed_at", ASCENDING)], name="zone_time"),
        IndexModel([("observed_at", DESCENDING)], name="time"),
    ],
    "storage_alerts": [
        IndexModel(
            [("zone_id", ASCENDING), ("kind", ASCENDING), ("status", ASCENDING)],
            name="zone_kind_status",
        ),
        IndexModel([("org_id", ASCENDING), ("updated_at", DESCENDING)], name="org_updated"),
        IndexModel([("affected_farmer_ids", ASCENDING)], name="farmers"),
    ],
    "inspection_records": [IndexModel([("alert_id", ASCENDING)], name="alert")],
    # Emergency + AquaSentinel (M6)
    "emergency_events": [
        IndexModel([("scenario_id", ASCENDING), ("status", ASCENDING)], name="scenario_status")
    ],
    "relocation_plans": [
        IndexModel([("event_id", ASCENDING), ("urgency", ASCENDING)], name="event_urgency"),
        IndexModel([("org_id", ASCENDING)], name="org"),
        IndexModel([("farmer_id", ASCENDING)], name="farmer"),
    ],
    "weather_alerts": [
        IndexModel(
            [
                ("target_type", ASCENDING),
                ("target_id", ASCENDING),
                ("date", ASCENDING),
                ("label", ASCENDING),
            ],
            unique=True,
            name="target_date_label",
        ),
        IndexModel([("owner_id", ASCENDING)], name="owner"),
        IndexModel([("org_id", ASCENDING)], name="org"),
    ],
    "notifications": [
        IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"),
        IndexModel([("user_id", ASCENDING), ("read_at", ASCENDING)], name="user_unread"),
    ],
}


# Indexes removed by later changes; dropped if present (dropping an index deletes no data).
OBSOLETE: dict[str, list[str]] = {
    # Login moved from phone to email (owner decision 2026-11-14). A unique phone index would
    # reject the second phone-less account, so it must go.
    "users": ["phone_unique"],
}


async def ensure_indexes(db: AsyncDatabase[Doc]) -> None:
    for collection, names in OBSOLETE.items():
        existing = {i["name"] async for i in await db[collection].list_indexes()}
        for name in names:
            if name in existing:
                await db[collection].drop_index(name)
    for collection, models in INDEXES.items():
        await db[collection].create_indexes(models)
