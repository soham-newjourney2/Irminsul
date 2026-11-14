"""Cached road distance (OSRM, 30-day cache) with the labelled Haversine x 1.3 fallback."""

from datetime import UTC, datetime, timedelta

from pymongo.asynchronous.database import AsyncDatabase

from backend.app.config import get_settings
from backend.app.core.geo import GeoPoint
from backend.app.db.client import Doc
from backend.app.integrations import osrm

ROUTE_TTL = timedelta(days=30)


async def cached_distance(db: AsyncDatabase[Doc], a: GeoPoint, b: GeoPoint) -> osrm.Distance:
    key = f"{a.lat:.3f},{a.lng:.3f}>{b.lat:.3f},{b.lng:.3f}"
    hit = await db.route_cache.find_one({"key": key})
    if hit and hit["fetched_at"] > datetime.now(UTC) - ROUTE_TTL:
        return osrm.Distance(
            km=hit["km"], source=hit["source"], duration_min=hit.get("duration_min")
        )
    d = await osrm.road_distance(
        a.lat, a.lng, b.lat, b.lng, timeout_s=get_settings().http_timeout_s
    )
    if d.source == "osrm":  # only cache real routes; estimates are recomputed cheaply
        await db.route_cache.update_one(
            {"key": key},
            {
                "$set": {
                    "key": key,
                    "km": d.km,
                    "source": d.source,
                    "duration_min": d.duration_min,
                    "fetched_at": datetime.now(UTC),
                }
            },
            upsert=True,
        )
    return d
