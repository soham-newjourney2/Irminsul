from typing import Annotated

from fastapi import APIRouter, Depends

from backend.app.core.deps import Db, require_role
from backend.app.core.schemas import Envelope, parse_object_id
from backend.app.db.client import Doc
from backend.app.modules.farms import service
from backend.app.modules.farms.schemas import FarmIn, FarmOut, FarmUpdate

router = APIRouter(prefix="/farms", tags=["farms"])
Farmer = Annotated[Doc, Depends(require_role("farmer"))]


@router.post("", status_code=201, response_model=Envelope[FarmOut])
async def create_farm(body: FarmIn, farmer: Farmer, db: Db) -> Envelope[FarmOut]:
    return Envelope(data=await service.create(db, farmer, body))


@router.get("", response_model=Envelope[list[FarmOut]])
async def list_farms(farmer: Farmer, db: Db) -> Envelope[list[FarmOut]]:
    return Envelope(data=await service.list_mine(db, farmer))


@router.patch("/{farm_id}", response_model=Envelope[FarmOut])
async def update_farm(farm_id: str, body: FarmUpdate, farmer: Farmer, db: Db) -> Envelope[FarmOut]:
    oid = parse_object_id(farm_id, "farm")
    return Envelope(data=await service.update(db, farmer, oid, body))
