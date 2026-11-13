from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.app.db.client import mongo

router = APIRouter(tags=["health"])


class HealthData(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "unavailable", "not_configured"]


class HealthResponse(BaseModel):
    data: HealthData
    meta: dict[str, str] = {}


@router.get("/health", response_model=HealthResponse)
async def health() -> JSONResponse:
    if mongo.client is None:
        data = HealthData(status="degraded", db="not_configured")
    elif await mongo.ping():
        data = HealthData(status="ok", db="ok")
    else:
        data = HealthData(status="degraded", db="unavailable")
    code = 200 if data.status == "ok" else 503
    return JSONResponse(HealthResponse(data=data).model_dump(), status_code=code)
