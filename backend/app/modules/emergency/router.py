from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.app.core.audit import write_audit
from backend.app.core.deps import ActiveUser, Db, require_role
from backend.app.core.schemas import Envelope, parse_object_id
from backend.app.db.client import Doc
from backend.app.modules.aquasentinel import service as aqua
from backend.app.modules.emergency import service

router = APIRouter(prefix="/emergencies", tags=["emergencies"])
aqua_router = APIRouter(prefix="/aquasentinel", tags=["aquasentinel"])
weather_alerts_router = APIRouter(prefix="/weather/alerts", tags=["weather"])
demo_router = APIRouter(prefix="/admin/demo", tags=["admin"])
Admin = Annotated[Doc, Depends(require_role("admin"))]
Coordinator = Annotated[Doc, Depends(require_role("storage_operator", "admin"))]
Limit = Annotated[int, Query(ge=1, le=100)]
Obj = Envelope[dict[str, Any]]
Rows = Envelope[list[dict[str, Any]]]


class TriggerIn(BaseModel):
    scenario_id: str = Field(min_length=1, max_length=60)


class ConfirmIn(BaseModel):
    facility_id: str


@router.get("", response_model=Rows)
async def list_events(user: ActiveUser, db: Db, limit: Limit = 20) -> Rows:
    return Envelope(data=await service.list_events(db, limit))


@router.get("/{event_id}/exposure", response_model=Obj)
async def exposure(event_id: str, user: ActiveUser, db: Db) -> Obj:
    return Envelope(data=await service.exposure(db, user, parse_object_id(event_id, "emergency")))


@router.get("/{event_id}/relocations", response_model=Rows)
async def relocations(
    event_id: str,
    user: ActiveUser,
    db: Db,
    rate_per_km_per_quintal: Annotated[Decimal | None, Query(ge=0, le=1000)] = None,
) -> Rows:
    rows = await service.list_plans(
        db, user, parse_object_id(event_id, "emergency"), rate_per_km_per_quintal
    )
    meta = {
        "ranking": (
            "Options: stores outside the scenario area that take the crop and have room, "
            "nearest by road first."
        ),
        "urgency_assumption": (
            "Lots are ordered by perishability (tomato, then potato, then rice/jute), "
            "an Irminsul assumption."
        ),
        "cost": "Shown only when you enter your own transport rate.",
    }
    return Envelope(data=rows, meta=meta)


@router.post("/relocations/{plan_id}/confirm", response_model=Obj)
async def confirm(plan_id: str, body: ConfirmIn, user: Coordinator, db: Db) -> Obj:
    out = await service.confirm(
        db, user, parse_object_id(plan_id, "plan"), parse_object_id(body.facility_id, "facility")
    )
    return Envelope(data=out)


@router.post("/{event_id}/close", response_model=Obj)
async def close(event_id: str, admin: Admin, db: Db) -> Obj:
    return Envelope(data=await service.close(db, admin, parse_object_id(event_id, "emergency")))


@aqua_router.get("/observations", response_model=Rows)
async def observations(user: ActiveUser, db: Db) -> Rows:
    rows = await aqua.rainfall_layer(db, user)
    return Envelope(
        data=rows,
        meta={
            "layers": ["rainfall_forecast"],
            "water_quality": "not available — no public source found",
        },
    )


@weather_alerts_router.get("", response_model=Rows)
async def weather_alerts(user: ActiveUser, db: Db, limit: Limit = 50) -> Rows:
    return Envelope(data=await aqua.list_alerts(db, user, limit))


@demo_router.get("/flood/scenarios", response_model=Rows)
async def list_scenarios(admin: Admin) -> Rows:
    rows = [{k: v for k, v in s.items()} for s in service.scenarios().values()]
    return Envelope(data=rows)


@demo_router.post("/flood/trigger", response_model=Obj)
async def trigger(body: TriggerIn, admin: Admin, db: Db) -> Obj:
    event = await service.trigger(db, admin, body.scenario_id)
    return Envelope(data=service.event_view(event))


@demo_router.post("/weather/check", response_model=Obj)
async def weather_check(admin: Admin, db: Db) -> Obj:
    new = await aqua.check_heavy_rain(db)
    await write_audit(
        db,
        actor_id=admin["_id"],
        action="demo.weather_check",
        target_type="weather_alerts",
        target_id=admin["_id"],
        details={"new_alerts": new},
    )
    return Envelope(data={"new_alerts": new})
