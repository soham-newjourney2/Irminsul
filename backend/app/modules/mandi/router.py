from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.app.core.audit import write_audit
from backend.app.core.deps import ActiveUser, Db, require_role
from backend.app.core.errors import AppError
from backend.app.core.geo import GeoPoint
from backend.app.core.reference import Commodity, validate_district
from backend.app.core.schemas import Envelope, parse_object_id
from backend.app.core.units import QtyIn, Unit, to_kg
from backend.app.db.client import Doc
from backend.app.modules.mandi import service

mandi_router = APIRouter(prefix="/mandi-prices", tags=["mandi-prices"])
markets_router = APIRouter(prefix="/markets", tags=["markets"])
admin_mandi_router = APIRouter(prefix="/admin/mandi", tags=["admin"])
Farmer = Annotated[Doc, Depends(require_role("farmer"))]
Admin = Annotated[Doc, Depends(require_role("admin"))]
Rows = Envelope[list[dict[str, Any]]]


@mandi_router.get("/latest", response_model=Rows)
async def latest(
    user: ActiveUser,
    db: Db,
    crop: Commodity,
    district: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Rows:
    try:
        d = validate_district(district) if district else None
    except ValueError as exc:
        raise AppError(422, "validation_error", str(exc)) from None
    rows = await service.latest_prices(db, crop, d, limit)
    return Envelope(data=rows, meta=await service.freshness(db))


@mandi_router.get("/history", response_model=Envelope[dict[str, Any]])
async def history(
    user: ActiveUser,
    db: Db,
    crop: Commodity,
    market_key: Annotated[str, Query(min_length=3, max_length=120)],
    days: Annotated[int, Query(ge=7, le=365)] = 90,
) -> Envelope[dict[str, Any]]:
    return Envelope(
        data=await service.history(db, crop, market_key, days), meta=await service.freshness(db)
    )


@mandi_router.get("/freshness", response_model=Envelope[dict[str, Any]])
async def freshness(user: ActiveUser, db: Db) -> Envelope[dict[str, Any]]:
    return Envelope(data=await service.freshness(db))


class NetRealizationIn(BaseModel):
    farm_id: str
    crop: Commodity
    qty: QtyIn
    unit: Unit
    transport_rate_per_km_per_quintal: Decimal = Field(ge=0, le=1000, decimal_places=2)
    fees_pct: float = Field(ge=0, le=100)
    practical_distance_km: float = Field(gt=0, le=1000)
    max_markets: int = Field(default=5, ge=1, le=10)
    distance: Literal["road"] = "road"


@markets_router.post("/net-realization", response_model=Rows)
async def net_realization(body: NetRealizationIn, farmer: Farmer, db: Db) -> Rows:
    farm = await db.farms.find_one(
        {"_id": parse_object_id(body.farm_id, "farm"), "farmer_id": farmer["_id"]}
    )
    if farm is None:
        raise AppError(404, "not_found", "Farm not found")
    lng, lat = farm["location"]["coordinates"]
    try:
        qty_kg = to_kg(body.qty, body.unit)
    except ValueError as exc:
        raise AppError(422, "validation_error", str(exc)) from None
    rate = (
        int((body.transport_rate_per_km_per_quintal * 100).to_integral_value())
        if body.transport_rate_per_km_per_quintal > 0
        else 0
    )
    rows = await service.net_realization(
        db,
        GeoPoint(lat=lat, lng=lng),
        body.crop,
        qty_kg,
        rate,
        body.fees_pct,
        body.practical_distance_km,
        body.max_markets,
    )
    meta = {
        "assumptions": {
            "qty_kg": qty_kg,
            "transport_rate_paise_per_km_per_quintal": rate,
            "fees_pct": body.fees_pct,
            "practical_distance_km": body.practical_distance_km,
            "price_used": "latest modal price per market (see arrival_date)",
            "market_positions": "approximate (OpenStreetMap geocoding of market names)",
        },
        **(await service.freshness(db)),
    }
    return Envelope(data=rows, meta=meta)


@markets_router.get("", response_model=Rows)
async def list_markets(user: ActiveUser, db: Db, crop: Commodity | None = None) -> Rows:
    query: Doc = {"crops": crop} if crop else {}
    rows = await db.markets.find(query, {"_id": 0}).sort("key", 1).to_list(500)
    for r in rows:
        loc = r.pop("location", None)
        r["location"] = (
            {"lat": loc["coordinates"][1], "lng": loc["coordinates"][0]} if loc else None
        )
    return Envelope(data=rows, meta={"count": len(rows)})


@admin_mandi_router.post("/refresh", response_model=Envelope[dict[str, Any]])
async def refresh(admin: Admin, db: Db) -> Envelope[dict[str, Any]]:
    """Reloads the dated snapshot (idempotent). Live API ingestion stays off until verified."""
    result = await service.load_snapshot(db)
    await write_audit(
        db,
        actor_id=admin["_id"],
        action="mandi.refresh",
        target_type="price_observations",
        target_id=admin["_id"],
        details={k: v for k, v in result.items() if k != "arrival_date_range"},
    )
    return Envelope(data=result, meta=await service.freshness(db))
