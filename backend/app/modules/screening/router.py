from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response

from backend.app.core.deps import Db, require_role
from backend.app.core.idempotency import IdempotencyKey, run_idempotent
from backend.app.core.reference import Commodity
from backend.app.core.schemas import Envelope, parse_object_id
from backend.app.db.client import Doc
from backend.app.modules.screening import service
from backend.app.modules.screening.schemas import ScreeningOut

router = APIRouter(prefix="/crop-screenings", tags=["crop-screenings"])
Farmer = Annotated[Doc, Depends(require_role("farmer"))]


@router.post("", status_code=201, response_model=Envelope[ScreeningOut])
async def create_screening(
    farmer: Farmer,
    db: Db,
    crop: Annotated[Commodity, Form()],
    image: Annotated[UploadFile, File()],
    batch_id: Annotated[str | None, Form()] = None,
    key: IdempotencyKey = None,
) -> Envelope[ScreeningOut]:
    out = await run_idempotent(
        db,
        user_id=farmer["_id"],
        key=key,
        scope="crop_screenings.create",
        model=ScreeningOut,
        fn=lambda: service.screen(db, farmer, crop, image, batch_id),
    )
    return Envelope(data=out)


@router.get("", response_model=Envelope[list[ScreeningOut]])
async def my_screenings(
    farmer: Farmer, db: Db, limit: Annotated[int, Query(ge=1, le=100)] = 30
) -> Envelope[list[ScreeningOut]]:
    return Envelope(data=await service.list_mine(db, farmer, limit))


@router.get("/{screening_id}", response_model=Envelope[ScreeningOut])
async def get_screening(screening_id: str, farmer: Farmer, db: Db) -> Envelope[ScreeningOut]:
    sid = parse_object_id(screening_id, "screening")
    return Envelope(data=await service.get(db, farmer, sid))


@router.get("/{screening_id}/image", response_class=Response)
async def screening_image(screening_id: str, farmer: Farmer, db: Db) -> Response:
    sid = parse_object_id(screening_id, "screening")
    data = await service.image_bytes(db, farmer, sid)
    return Response(
        data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"}
    )
