from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.app.core.deps import ActiveUser, Db, require_role
from backend.app.core.errors import AppError
from backend.app.core.geo import parse_near
from backend.app.core.idempotency import IdempotencyKey, run_idempotent
from backend.app.core.reference import Commodity, validate_district
from backend.app.core.schemas import Envelope, parse_object_id
from backend.app.db.client import Doc
from backend.app.modules.storage import service
from backend.app.modules.storage.schemas import (
    BookingIn,
    BookingOut,
    BookingStatus,
    CheckInIn,
    DecisionIn,
    FacilityIn,
    FacilityOut,
    FacilityUpdate,
    ResubmitIn,
    ZoneIn,
    ZoneOut,
)

router = APIRouter(prefix="/storage", tags=["storage"])
Operator = Annotated[Doc, Depends(require_role("storage_operator"))]
Farmer = Annotated[Doc, Depends(require_role("farmer"))]
Party = Annotated[Doc, Depends(require_role("farmer", "storage_operator"))]
Limit = Annotated[int, Query(ge=1, le=100)]
BOut = Envelope[BookingOut]


# --- facilities ---------------------------------------------------------------


@router.post("/facilities", status_code=201, response_model=Envelope[FacilityOut])
async def create_facility(body: FacilityIn, operator: Operator, db: Db) -> Envelope[FacilityOut]:
    return Envelope(data=await service.create_facility(db, operator, body))


@router.get("/facilities", response_model=Envelope[list[FacilityOut]])
async def search_facilities(
    user: ActiveUser,
    db: Db,
    commodity: Commodity | None = None,
    district: str | None = None,
    near: Annotated[str | None, Query(description="lat,lng")] = None,
    radius_km: Annotated[float, Query(gt=0, le=500)] = 100,
    min_free_kg: Annotated[int | None, Query(ge=1)] = None,
    limit: Limit = 100,
) -> Envelope[list[FacilityOut]]:
    try:
        point = parse_near(near)
        district_v = validate_district(district) if district else None
    except ValueError as exc:
        raise AppError(422, "validation_error", str(exc)) from None
    rows = await service.search_facilities(
        db,
        user,
        commodity=commodity,
        district=district_v,
        near=point,
        radius_km=radius_km,
        min_free_kg=min_free_kg,
        limit=limit,
    )
    return Envelope(data=rows, meta={"count": len(rows), "limit": limit})


@router.get("/facilities/mine", response_model=Envelope[list[FacilityOut]])
async def my_facilities(operator: Operator, db: Db) -> Envelope[list[FacilityOut]]:
    return Envelope(data=await service.list_my_facilities(db, operator))


@router.get("/facilities/{facility_id}", response_model=Envelope[FacilityOut])
async def get_facility(facility_id: str, user: ActiveUser, db: Db) -> Envelope[FacilityOut]:
    fid = parse_object_id(facility_id, "facility")
    return Envelope(data=await service.get_facility(db, user, fid))


@router.patch("/facilities/{facility_id}", response_model=Envelope[FacilityOut])
async def update_facility(
    facility_id: str, body: FacilityUpdate, operator: Operator, db: Db
) -> Envelope[FacilityOut]:
    fid = parse_object_id(facility_id, "facility")
    return Envelope(data=await service.update_facility(db, operator, fid, body))


@router.post("/facilities/{facility_id}/zones", status_code=201, response_model=Envelope[ZoneOut])
async def create_zone(
    facility_id: str, body: ZoneIn, operator: Operator, db: Db
) -> Envelope[ZoneOut]:
    fid = parse_object_id(facility_id, "facility")
    return Envelope(data=await service.create_zone(db, operator, fid, body))


@router.get("/facilities/{facility_id}/zones", response_model=Envelope[list[ZoneOut]])
async def list_zones(facility_id: str, user: ActiveUser, db: Db) -> Envelope[list[ZoneOut]]:
    fid = parse_object_id(facility_id, "facility")
    await service.get_facility(db, user, fid)  # visibility check
    return Envelope(data=await service.list_zones(db, fid))


# --- bookings -----------------------------------------------------------------


@router.post("/bookings", status_code=201, response_model=BOut)
async def create_booking(
    body: BookingIn, farmer: Farmer, db: Db, key: IdempotencyKey = None
) -> BOut:
    out = await run_idempotent(
        db,
        user_id=farmer["_id"],
        key=key,
        scope="storage_bookings.create",
        model=BookingOut,
        fn=lambda: service.create_booking(db, farmer, body),
    )
    return Envelope(data=out)


@router.get("/bookings", response_model=Envelope[list[BookingOut]])
async def list_bookings(
    user: Party,
    db: Db,
    status: BookingStatus | None = None,
    facility_id: str | None = None,
    limit: Limit = 50,
) -> Envelope[list[BookingOut]]:
    fid = parse_object_id(facility_id, "facility") if facility_id else None
    rows = await service.list_bookings(db, user, status, fid, limit)
    return Envelope(data=rows, meta={"count": len(rows), "limit": limit})


@router.get("/bookings/{booking_id}", response_model=BOut)
async def get_booking(booking_id: str, user: Party, db: Db) -> BOut:
    return Envelope(
        data=await service.get_booking(db, user, parse_object_id(booking_id, "booking"))
    )


def _simple_action(action: str) -> None:
    async def endpoint(booking_id: str, body: DecisionIn, user: Party, db: Db) -> BOut:
        bid = parse_object_id(booking_id, "booking")
        return Envelope(data=await service.booking_action(db, user, bid, action, note=body.note))

    router.add_api_route(
        f"/bookings/{{booking_id}}/{action}",
        endpoint,
        methods=["POST"],
        response_model=BOut,
        name=f"booking_{action.replace('-', '_')}",
    )


for _action in ("accept", "reject", "request-changes", "release", "cancel"):
    _simple_action(_action)


@router.post("/bookings/{booking_id}/check-in", response_model=BOut)
async def check_in(booking_id: str, body: CheckInIn, user: Party, db: Db) -> BOut:
    bid = parse_object_id(booking_id, "booking")
    out = await service.booking_action(
        db, user, bid, "check-in", note=body.note, zone_id=body.zone_id
    )
    return Envelope(data=out)


@router.post("/bookings/{booking_id}/resubmit", response_model=BOut)
async def resubmit(booking_id: str, body: ResubmitIn, user: Party, db: Db) -> BOut:
    bid = parse_object_id(booking_id, "booking")
    return Envelope(data=await service.booking_action(db, user, bid, "resubmit", resubmit=body))
