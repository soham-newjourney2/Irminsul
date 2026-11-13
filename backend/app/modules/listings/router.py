from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.app.core.deps import ActiveUser, Db, require_role
from backend.app.core.errors import AppError
from backend.app.core.geo import parse_near
from backend.app.core.idempotency import IdempotencyKey, run_idempotent
from backend.app.core.reference import Commodity, validate_district
from backend.app.core.schemas import Envelope, parse_object_id
from backend.app.core.units import MAX_PRICE_RUPEES_PER_QUINTAL
from backend.app.db.client import Doc
from backend.app.modules.listings import service
from backend.app.modules.listings.schemas import ListingIn, ListingOut, ListingUpdate

router = APIRouter(prefix="/listings", tags=["listings"])
Farmer = Annotated[Doc, Depends(require_role("farmer"))]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.post("", status_code=201, response_model=Envelope[ListingOut])
async def create_listing(
    body: ListingIn, farmer: Farmer, db: Db, key: IdempotencyKey = None
) -> Envelope[ListingOut]:
    out = await run_idempotent(
        db,
        user_id=farmer["_id"],
        key=key,
        scope="listings.create",
        model=ListingOut,
        fn=lambda: service.create(db, farmer, body),
    )
    return Envelope(data=out)


@router.get("", response_model=Envelope[list[ListingOut]])
async def search_listings(
    user: ActiveUser,
    db: Db,
    commodity: Commodity | None = None,
    district: str | None = None,
    near: Annotated[str | None, Query(description="lat,lng")] = None,
    radius_km: Annotated[float, Query(gt=0, le=500)] = 50,
    min_qty_kg: Annotated[int | None, Query(ge=1)] = None,
    max_price_per_quintal: Annotated[float | None, Query(gt=0)] = None,
    sort: service.SortKey = "newest",
    limit: Limit = 50,
) -> Envelope[list[ListingOut]]:
    try:
        point = parse_near(near)
        district_v = validate_district(district) if district else None
    except ValueError as exc:
        raise AppError(422, "validation_error", str(exc)) from None
    if sort == "distance" and point is None:
        raise AppError(422, "validation_error", "sort=distance needs near=lat,lng")
    max_paise = None
    if max_price_per_quintal is not None:
        max_paise = int(min(max_price_per_quintal, float(MAX_PRICE_RUPEES_PER_QUINTAL)) * 100)
    rows = await service.search(
        db,
        user,
        commodity=commodity,
        district=district_v,
        near=point,
        radius_km=radius_km,
        min_qty_kg=min_qty_kg,
        max_price_paise=max_paise,
        sort=sort,
        limit=limit,
    )
    meta = {"count": len(rows), "limit": limit}
    if point is not None:
        meta |= {"near": near, "radius_km": radius_km}
    return Envelope(data=rows, meta=meta)


@router.get("/mine", response_model=Envelope[list[ListingOut]])
async def my_listings(farmer: Farmer, db: Db, limit: Limit = 100) -> Envelope[list[ListingOut]]:
    return Envelope(data=await service.list_mine(db, farmer, limit))


@router.get("/{listing_id}", response_model=Envelope[ListingOut])
async def get_listing(listing_id: str, user: ActiveUser, db: Db) -> Envelope[ListingOut]:
    return Envelope(data=await service.get(db, user, parse_object_id(listing_id, "listing")))


@router.patch("/{listing_id}", response_model=Envelope[ListingOut])
async def update_listing(
    listing_id: str, body: ListingUpdate, farmer: Farmer, db: Db
) -> Envelope[ListingOut]:
    oid = parse_object_id(listing_id, "listing")
    return Envelope(data=await service.update(db, farmer, oid, body))


@router.post("/{listing_id}/publish", response_model=Envelope[ListingOut])
async def publish_listing(listing_id: str, farmer: Farmer, db: Db) -> Envelope[ListingOut]:
    oid = parse_object_id(listing_id, "listing")
    return Envelope(data=await service.publish(db, farmer, oid))


@router.post("/{listing_id}/cancel", response_model=Envelope[ListingOut])
async def cancel_listing(listing_id: str, farmer: Farmer, db: Db) -> Envelope[ListingOut]:
    oid = parse_object_id(listing_id, "listing")
    return Envelope(data=await service.cancel(db, farmer, oid))
