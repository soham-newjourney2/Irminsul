"""AquaSentinel: persisted heavy-rain alerts + the rainfall map layer (Open-Meteo, real data).

The water-quality layer is cut (no public source found; planning §12 cut-list item 3).
"""

import logging
from datetime import UTC, datetime
from typing import Any

from pymongo import DESCENDING
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from backend.app.core.errors import AppError
from backend.app.core.geo import GeoPoint, point_out
from backend.app.db.client import Doc
from backend.app.integrations import open_meteo
from backend.app.modules.notifications.service import notify, org_member_ids
from backend.app.modules.weather import service as weather

log = logging.getLogger("irminsul.aquasentinel")
MAX_POINTS_PER_RUN = 200
MAX_FRESH_FETCHES_PER_LAYER = 10


async def _points(db: AsyncDatabase[Doc]) -> list[tuple[str, Doc]]:
    farms = await db.farms.find(
        {}, {"name": 1, "district": 1, "location": 1, "farmer_id": 1}
    ).to_list(MAX_POINTS_PER_RUN)
    facs = await db.storage_facilities.find(
        {"status": "active"}, {"name": 1, "district": 1, "location": 1, "org_id": 1}
    ).to_list(MAX_POINTS_PER_RUN)
    return [("farm", f) for f in farms] + [("facility", f) for f in facs]


async def check_heavy_rain(db: AsyncDatabase[Doc]) -> int:
    """Store heavy-rain alerts (one per place/day/band) and notify owners; returns new count."""
    new = 0
    for target_type, doc in (await _points(db))[:MAX_POINTS_PER_RUN]:
        p = point_out(doc["location"])
        try:
            data, _, stale = await weather.get_forecast(db, GeoPoint(lat=p.lat, lng=p.lng))
        except AppError:
            continue
        for a in weather.advisories_for(data, []):
            if a.rule_id != "heavy_rain":
                continue
            alert: Doc = {
                "schema_version": 1,
                "target_type": target_type,
                "target_id": doc["_id"],
                "target_name": doc["name"],
                "district": doc["district"],
                "owner_id": doc.get("farmer_id"),
                "org_id": doc.get("org_id"),
                "date": a.evidence["date"],
                "label": a.label,
                "severity": a.severity,
                "precipitation_mm": a.evidence["precipitation_mm"],
                "threshold_mm": a.evidence["threshold_mm"],
                "verified": a.verified,
                "source": open_meteo.SOURCE,
                "rule_source": a.source,
                "forecast_fetched_at": data["fetched_at"],
                "stale_forecast": stale,
                "created_at": datetime.now(UTC),
            }
            try:
                await db.weather_alerts.insert_one(alert)
            except DuplicateKeyError:
                continue
            new += 1
            params = {
                "place": doc["name"],
                "mm": a.evidence["precipitation_mm"],
                "date": a.evidence["date"],
                "label": a.label,
            }
            recipients = (
                [doc["farmer_id"]]
                if target_type == "farm"
                else await org_member_ids(db, doc["org_id"])
            )
            await notify(
                db,
                recipients,
                "weather.heavy_rain",
                params,
                "/farmer/weather.html" if target_type == "farm" else "/storage/facilities.html",
            )
    return new


def _alert_view(a: Doc) -> dict[str, Any]:
    return {
        "id": str(a["_id"]),
        "target_type": a["target_type"],
        "target_id": str(a["target_id"]),
        "target_name": a["target_name"],
        "district": a["district"],
        "date": a["date"],
        "label": a["label"],
        "severity": a["severity"],
        "precipitation_mm": a["precipitation_mm"],
        "threshold_mm": a["threshold_mm"],
        "verified": a["verified"],
        "source": a["source"],
        "rule_source": a["rule_source"],
        "forecast_fetched_at": a["forecast_fetched_at"],
        "stale_forecast": a["stale_forecast"],
        "created_at": a["created_at"],
    }


async def list_alerts(db: AsyncDatabase[Doc], user: Doc, limit: int) -> list[dict[str, Any]]:
    if user["role"] == "farmer":
        query: Doc = {"owner_id": user["_id"]}
    elif user["role"] == "storage_operator":
        query = {"org_id": user.get("org_id")}
    elif user["role"] == "admin":
        query = {}
    else:
        return []
    rows = await db.weather_alerts.find(query).sort("created_at", DESCENDING).to_list(limit)
    return [_alert_view(a) for a in rows]


async def rainfall_layer(db: AsyncDatabase[Doc], user: Doc) -> list[dict[str, Any]]:
    """Forecast rainfall at the user's own farms / facilities (admin: all), mostly from cache."""
    if user["role"] == "farmer":
        pts = [("farm", f) for f in await db.farms.find({"farmer_id": user["_id"]}).to_list(100)]
    elif user["role"] == "storage_operator":
        pts = [
            ("facility", f)
            for f in await db.storage_facilities.find({"org_id": user.get("org_id")}).to_list(100)
        ]
    elif user["role"] == "admin":
        pts = await _points(db)
    else:
        pts = []
    out, fresh = [], 0
    for target_type, doc in pts:
        p = point_out(doc["location"])
        gp = GeoPoint(lat=p.lat, lng=p.lng)
        cached = await db.weather_cache.find_one({"key": f"{gp.lat:.2f},{gp.lng:.2f}"})
        if cached is None and fresh >= MAX_FRESH_FETCHES_PER_LAYER:
            continue
        try:
            data, was_cached, stale = await weather.get_forecast(db, gp)
        except AppError:
            continue
        fresh += 0 if was_cached else 1
        daily = data["daily"]
        out.append(
            {
                "target_type": target_type,
                "name": doc["name"],
                "district": doc["district"],
                "location": {"lat": p.lat, "lng": p.lng},
                "today_mm": daily["precipitation_sum"][0],
                "next_3_days_mm": round(sum(v or 0 for v in daily["precipitation_sum"]), 1),
                "fetched_at": data["fetched_at"],
                "source": open_meteo.SOURCE,
                "attribution": open_meteo.ATTRIBUTION,
                "kind": "forecast",
                "spatial_resolution": (
                    "weather-model grid cell containing the point (Open-Meteo best-match model)"
                ),
                "confidence": "forecast — not an observation",
                "stale": stale,
            }
        )
    return out
