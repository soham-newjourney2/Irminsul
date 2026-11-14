from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from backend.app.core.audit import write_audit
from backend.app.core.deps import ActiveUser, Db, require_role
from backend.app.core.idempotency import IdempotencyKey, run_idempotent
from backend.app.core.schemas import Envelope, parse_object_id
from backend.app.db.client import Doc
from backend.app.modules.freshtrack import rules, service, simulator
from backend.app.modules.freshtrack.schemas import (
    AckIn,
    AlertOut,
    AlertStatus,
    InjectIn,
    ObservationIn,
    ObservationOut,
    ObservationsOut,
    ResolveIn,
    SimulatorIn,
)

router = APIRouter(prefix="/freshtrack", tags=["freshtrack"])
demo_router = APIRouter(prefix="/admin/demo/freshtrack", tags=["admin"])
Operator = Annotated[Doc, Depends(require_role("storage_operator", "admin"))]
Admin = Annotated[Doc, Depends(require_role("admin"))]
Limit = Annotated[int, Query(ge=1, le=100)]


class _CreateOut(ObservationOut):
    alerts: list[AlertOut]


@router.get("/rules", response_model=Envelope[dict[str, Any]])
async def get_rules(user: ActiveUser) -> Envelope[dict[str, Any]]:
    return Envelope(data=rules.load())


@router.post("/observations", status_code=201, response_model=Envelope[_CreateOut])
async def create_observation(
    body: ObservationIn, user: Operator, db: Db, key: IdempotencyKey = None
) -> Envelope[_CreateOut]:
    async def run() -> _CreateOut:
        obs, alerts = await service.add_observation(db, user, body)
        return _CreateOut(**obs.model_dump(), alerts=alerts)

    out = await run_idempotent(
        db,
        user_id=user["_id"],
        key=key,
        scope="freshtrack.observations.create",
        model=_CreateOut,
        fn=run,
    )
    return Envelope(data=out)


@router.get("/observations", response_model=Envelope[ObservationsOut])
async def observations(
    user: ActiveUser, db: Db, zone_id: str, hours: Annotated[int, Query(ge=1, le=168)] = 24
) -> Envelope[ObservationsOut]:
    data = await service.list_observations(db, user, parse_object_id(zone_id, "zone"), hours)
    return Envelope(data=ObservationsOut(**data))


@router.get("/alerts", response_model=Envelope[list[AlertOut]])
async def alerts(
    user: ActiveUser,
    db: Db,
    status: AlertStatus | None = None,
    zone_id: str | None = None,
    limit: Limit = 50,
) -> Envelope[list[AlertOut]]:
    zid = parse_object_id(zone_id, "zone") if zone_id else None
    rows = await service.list_alerts(db, user, status, zid, limit)
    return Envelope(
        data=rows, meta={"count": len(rows), "assumptions": rules.defaults()["assumptions"]}
    )


@router.post("/alerts/{alert_id}/acknowledge", response_model=Envelope[AlertOut])
async def acknowledge(alert_id: str, body: AckIn, user: Operator, db: Db) -> Envelope[AlertOut]:
    return Envelope(
        data=await service.acknowledge(db, user, parse_object_id(alert_id, "alert"), body.note)
    )


@router.post("/alerts/{alert_id}/resolve", response_model=Envelope[AlertOut])
async def resolve(alert_id: str, body: ResolveIn, user: Operator, db: Db) -> Envelope[AlertOut]:
    out = await service.resolve(
        db,
        user,
        parse_object_id(alert_id, "alert"),
        body.findings,
        body.corrective_action,
        body.inspected_at,
    )
    return Envelope(data=out)


# --- admin demo panel ---------------------------------------------------------------------------


async def _demo_audit(
    db: Db, admin: Doc, action: str, zone_id: Any, details: dict[str, Any]
) -> None:
    await write_audit(
        db,
        actor_id=admin["_id"],
        action=f"demo.{action}",
        target_type="storage_zone",
        target_id=zone_id,
        details=details,
    )


@demo_router.get("/simulator", response_model=Envelope[dict[str, Any]])
async def simulator_status(admin: Admin) -> Envelope[dict[str, Any]]:
    return Envelope(data={"running_zone_ids": simulator.running()})


@demo_router.post("/simulator/start", response_model=Envelope[dict[str, Any]])
async def simulator_start(body: SimulatorIn, admin: Admin, db: Db) -> Envelope[dict[str, Any]]:
    zid = parse_object_id(body.zone_id, "zone")
    await service.zone_context(db, zid)
    started = simulator.start(db, zid, body.interval_s)
    await _demo_audit(
        db, admin, "simulator.start", zid, {"interval_s": body.interval_s, "started": started}
    )
    return Envelope(data={"started": started, "running_zone_ids": simulator.running()})


@demo_router.post("/simulator/stop", response_model=Envelope[dict[str, Any]])
async def simulator_stop(body: SimulatorIn, admin: Admin, db: Db) -> Envelope[dict[str, Any]]:
    zid = parse_object_id(body.zone_id, "zone")
    stopped = simulator.stop(zid)
    await _demo_audit(db, admin, "simulator.stop", zid, {"stopped": stopped})
    return Envelope(data={"stopped": stopped, "running_zone_ids": simulator.running()})


@demo_router.post("/inject", response_model=Envelope[list[AlertOut]])
async def inject(body: InjectIn, admin: Admin, db: Db) -> Envelope[list[AlertOut]]:
    zid = parse_object_id(body.zone_id, "zone")
    changed = await simulator.inject(db, zid, body.kind, body.minutes, body.magnitude)
    await _demo_audit(db, admin, "inject", zid, body.model_dump())
    return Envelope(data=await service.alert_views(db, changed))


@demo_router.post("/check-stale", response_model=Envelope[dict[str, Any]])
async def check_stale(
    admin: Admin, db: Db, minutes_ahead: Annotated[int, Query(ge=0, le=240)] = 0
) -> Envelope[dict[str, Any]]:
    """Runs the stale check now — or "as if" N minutes later (alerts then marked simulated)."""
    now = datetime.now(UTC) + timedelta(minutes=minutes_ahead)
    count = await service.check_stale(db, now, simulated=minutes_ahead > 0)
    await _demo_audit(
        db, admin, "check_stale", admin["_id"], {"minutes_ahead": minutes_ahead, "alerts": count}
    )
    return Envelope(
        data={"stale_zones": count, "as_of": now.isoformat(), "simulated_time": minutes_ahead > 0}
    )
