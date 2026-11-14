import io
from typing import Annotated

import qrcode
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from backend.app.config import get_settings
from backend.app.core.deps import ActiveUser, Db, require_role
from backend.app.core.schemas import Envelope, parse_object_id
from backend.app.db.client import Doc
from backend.app.modules.batches import service
from backend.app.modules.batches.schemas import (
    BatchDetailOut,
    BatchIn,
    BatchOut,
    CorrectionIn,
    PublicBatchOut,
    QrOut,
    SplitIn,
    VerifyOut,
)

router = APIRouter(prefix="/batches", tags=["batches"])
public_router = APIRouter(prefix="/qr", tags=["batches"])
Farmer = Annotated[Doc, Depends(require_role("farmer"))]
Owner = Annotated[Doc, Depends(require_role("farmer", "admin"))]


def _verify_url(request: Request, token: str) -> str:
    base = get_settings().public_base_url or str(request.base_url)
    return f"{base.rstrip('/')}/verify.html?t={token}"


@router.post("", status_code=201, response_model=Envelope[BatchOut])
async def create_batch(body: BatchIn, farmer: Farmer, db: Db) -> Envelope[BatchOut]:
    return Envelope(data=await service.create(db, farmer, body))


@router.get("", response_model=Envelope[list[BatchOut]])
async def my_batches(
    farmer: Farmer, db: Db, limit: Annotated[int, Query(ge=1, le=100)] = 100
) -> Envelope[list[BatchOut]]:
    return Envelope(data=await service.list_mine(db, farmer, limit))


@router.get("/{batch_id}", response_model=Envelope[BatchDetailOut])
async def get_batch(batch_id: str, user: ActiveUser, db: Db) -> Envelope[BatchDetailOut]:
    return Envelope(data=await service.get_detail(db, user, parse_object_id(batch_id, "batch")))


@router.get("/{batch_id}/verify", response_model=Envelope[VerifyOut])
async def verify_batch(batch_id: str, user: ActiveUser, db: Db) -> Envelope[VerifyOut]:
    return Envelope(data=await service.verify(db, user, parse_object_id(batch_id, "batch")))


@router.post("/{batch_id}/events/{seq}/correct", response_model=Envelope[BatchDetailOut])
async def correct_event(
    batch_id: str, seq: int, body: CorrectionIn, user: ActiveUser, db: Db
) -> Envelope[BatchDetailOut]:
    bid = parse_object_id(batch_id, "batch")
    return Envelope(data=await service.correct(db, user, bid, seq, body))


@router.post("/{batch_id}/split", response_model=Envelope[BatchDetailOut])
async def split_batch(
    batch_id: str, body: SplitIn, farmer: Farmer, db: Db
) -> Envelope[BatchDetailOut]:
    bid = parse_object_id(batch_id, "batch")
    return Envelope(data=await service.split(db, farmer, bid, body))


@router.get("/{batch_id}/qr", response_model=Envelope[QrOut])
async def batch_qr(batch_id: str, request: Request, user: Owner, db: Db) -> Envelope[QrOut]:
    token = await service.qr_token(db, user, parse_object_id(batch_id, "batch"))
    return Envelope(data=QrOut(token=token, url=_verify_url(request, token)))


@router.get("/{batch_id}/qr.png", response_class=Response)
async def batch_qr_png(batch_id: str, request: Request, user: Owner, db: Db) -> Response:
    token = await service.qr_token(db, user, parse_object_id(batch_id, "batch"))
    img = qrcode.make(_verify_url(request, token), box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(
        buf.getvalue(), media_type="image/png", headers={"Cache-Control": "private, max-age=300"}
    )


@public_router.get("/{token}", response_model=Envelope[PublicBatchOut])
async def public_batch(token: str, db: Db) -> Envelope[PublicBatchOut]:
    """No login: what a mobile browser sees after scanning the QR code."""
    return Envelope(data=await service.public_view(db, token[:64]))
