"""Weather (Open-Meteo, cached 1 h per ~1 km cell), advisories, and sourced guidance lookup."""

import json
import logging
from datetime import UTC, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from backend.app.config import REPO_ROOT, get_settings
from backend.app.core.errors import AppError
from backend.app.core.geo import GeoPoint
from backend.app.db.client import Doc
from backend.app.integrations import open_meteo
from backend.app.modules.weather import engine
from backend.app.modules.weather.schemas import (
    AdvisoryOut,
    DailyOut,
    GuidanceOut,
    HourlyOut,
    WeatherOut,
)

log = logging.getLogger("irminsul.weather")
CACHE_TTL = timedelta(hours=1)
IST = timezone(timedelta(hours=5, minutes=30), "IST")  # Asia/Kolkata, no DST
GUIDANCE_PATH = REPO_ROOT / "ai" / "knowledge" / "guidance.json"


def _cell(p: GeoPoint) -> str:
    return f"{p.lat:.2f},{p.lng:.2f}"


async def get_forecast(
    db: AsyncDatabase[Doc], point: GeoPoint
) -> tuple[dict[str, Any], bool, bool]:
    """Returns (forecast, cached, stale). Serves stale cache when the provider is down."""
    key = _cell(point)
    now = datetime.now(UTC)
    cached = await db.weather_cache.find_one({"key": key})
    if cached and cached["fetched_at"] > now - CACHE_TTL:
        return cached["data"], True, False
    try:
        data = await open_meteo.fetch_forecast(
            point.lat, point.lng, timeout_s=get_settings().http_timeout_s
        )
    except open_meteo.WeatherUnavailable:
        log.warning("Open-Meteo unavailable for %s", key)
        if cached:
            return cached["data"], True, True
        raise AppError(
            503, "weather_unavailable", "Weather data is unavailable right now"
        ) from None
    await db.weather_cache.update_one(
        {"key": key},
        {"$set": {"key": key, "data": data, "fetched_at": now, "source": open_meteo.SOURCE}},
        upsert=True,
    )
    return data, False, False


def weather_out(point: GeoPoint, data: dict[str, Any], cached: bool, stale: bool) -> WeatherOut:
    d, h = data["daily"], data["hourly"]
    now_local = datetime.now(IST).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    hours = [
        HourlyOut(
            time=t,
            temp_c=h["temperature_2m"][i],
            rh_pct=h["relative_humidity_2m"][i],
            precipitation_mm=h["precipitation"][i],
        )
        for i, t in enumerate(h["time"])
        if datetime.fromisoformat(t) >= now_local
    ][:24]
    return WeatherOut(
        location=point,
        timezone=data.get("timezone", open_meteo.TIMEZONE),
        daily=[
            DailyOut(
                date=t,
                precipitation_mm=d["precipitation_sum"][i],
                temp_max_c=d["temperature_2m_max"][i],
                temp_min_c=d["temperature_2m_min"][i],
            )
            for i, t in enumerate(d["time"])
        ],
        next_hours=hours,
        source=open_meteo.SOURCE,
        attribution=open_meteo.ATTRIBUTION,
        fetched_at=datetime.fromisoformat(data["fetched_at"]),
        cached=cached,
        stale=stale,
    )


def advisories_for(data: dict[str, Any], crops: list[str]) -> list[AdvisoryOut]:
    now_local = datetime.now(IST).replace(tzinfo=None)
    found = engine.evaluate(data, crops, now_local, engine.load_rules())
    keys = set(guidance_entries())
    out = []
    for a in found:
        gk = f"{a.crop}.{a.disease}" if a.crop and a.disease else None
        out.append(
            AdvisoryOut(
                rule_id=a.rule_id,
                kind=a.kind,
                severity=a.severity,
                crop=a.crop,
                disease=a.disease,
                label=a.label,
                evidence=a.evidence,
                window_start=a.window_start,
                window_end=a.window_end,
                source=a.source,
                verified=a.verified,
                assumptions=a.assumptions,
                guidance_key=gk if gk in keys else None,
            )
        )
    return out


async def farm_point(db: AsyncDatabase[Doc], farmer: Doc, farm_id: Any) -> GeoPoint:
    farm = await db.farms.find_one({"_id": farm_id, "farmer_id": farmer["_id"]})
    if farm is None:
        raise AppError(404, "not_found", "Farm not found")
    lng, lat = farm["location"]["coordinates"]
    return GeoPoint(lat=lat, lng=lng)


# --- guidance KB -----------------------------------------------------------------


@lru_cache(maxsize=1)
def _guidance() -> dict[str, Any]:
    return json.loads(GUIDANCE_PATH.read_text(encoding="utf-8"))


def guidance_entries() -> dict[str, Any]:
    return _guidance()["entries"]


def guidance(key: str) -> GuidanceOut:
    kb = _guidance()
    entry = kb["entries"].get(key)
    if entry is None:
        raise AppError(404, "guidance_not_available", "No sourced guidance for this yet")
    meta = kb["meta"]
    return GuidanceOut(
        key=key,
        entry=entry,
        review_status=meta["review_status"],
        translation_status=meta["translation_status"],
        policy=meta["policy"],
    )
