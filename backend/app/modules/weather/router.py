import re
from typing import Annotated

from fastapi import APIRouter, Query

from backend.app.core.deps import ActiveUser, Db
from backend.app.core.errors import AppError
from backend.app.core.geo import GeoPoint
from backend.app.core.schemas import Envelope, parse_object_id
from backend.app.db.client import Doc
from backend.app.modules.weather import service
from backend.app.modules.weather.schemas import AdvisoryOut, GuidanceOut, WeatherOut

weather_router = APIRouter(prefix="/weather", tags=["weather"])
advisories_router = APIRouter(prefix="/advisories", tags=["advisories"])

ADVISORY_CROPS = ("potato", "tomato", "rice", "jute")
_KEY_PART = re.compile(r"^[a-z_]{2,40}$")


async def _point(
    db: Db, user: Doc, farm_id: str | None, lat: float | None, lng: float | None
) -> GeoPoint:
    if farm_id:
        if user["role"] != "farmer":
            raise AppError(403, "forbidden", "Only farmers can look up their farms")
        return await service.farm_point(db, user, parse_object_id(farm_id, "farm"))
    if lat is None or lng is None:
        raise AppError(422, "validation_error", "Give farm_id or lat and lng")
    try:
        return GeoPoint(lat=lat, lng=lng)
    except ValueError:
        raise AppError(422, "validation_error", "Location must be inside West Bengal") from None


@weather_router.get("", response_model=Envelope[WeatherOut])
async def weather(
    user: ActiveUser,
    db: Db,
    farm_id: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
) -> Envelope[WeatherOut]:
    point = await _point(db, user, farm_id, lat, lng)
    data, cached, stale = await service.get_forecast(db, point)
    return Envelope(data=service.weather_out(point, data, cached, stale))


@advisories_router.get("", response_model=Envelope[list[AdvisoryOut]])
async def advisories(
    user: ActiveUser,
    db: Db,
    farm_id: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    crops: Annotated[str, Query(max_length=60)] = "potato,tomato",
) -> Envelope[list[AdvisoryOut]]:
    wanted = [c for c in crops.split(",") if c in ADVISORY_CROPS]
    point = await _point(db, user, farm_id, lat, lng)
    data, cached, stale = await service.get_forecast(db, point)
    rows = service.advisories_for(data, wanted)
    return Envelope(
        data=rows,
        meta={
            "fetched_at": data["fetched_at"],
            "cached": cached,
            "stale": stale,
            "source": "open-meteo",
            "rules": "data/advisory_rules.json",
            "review_status": "not expert-reviewed",
        },
    )


@advisories_router.get("/guidance/{crop}/{disease}", response_model=Envelope[GuidanceOut])
async def guidance(crop: str, disease: str, user: ActiveUser) -> Envelope[GuidanceOut]:
    if not (_KEY_PART.fullmatch(crop) and _KEY_PART.fullmatch(disease)):
        raise AppError(404, "guidance_not_available", "No sourced guidance for this yet")
    return Envelope(data=service.guidance(f"{crop}.{disease}"))
