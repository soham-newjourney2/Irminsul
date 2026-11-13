from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from backend.app.core.geo import GeoPoint
from backend.app.core.reference import validate_district


class FarmIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    district: str
    village: str | None = Field(default=None, max_length=80)
    area_acres: Decimal | None = Field(default=None, gt=0, le=10_000, decimal_places=2)
    location: GeoPoint

    @field_validator("district")
    @classmethod
    def _district(cls, v: str) -> str:
        return validate_district(v)


class FarmUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    district: str | None = None
    village: str | None = Field(default=None, max_length=80)
    area_acres: Decimal | None = Field(default=None, gt=0, le=10_000, decimal_places=2)
    location: GeoPoint | None = None

    @field_validator("district")
    @classmethod
    def _district(cls, v: str | None) -> str | None:
        return validate_district(v) if v is not None else None


class FarmOut(BaseModel):
    id: str
    name: str
    district: str
    village: str | None
    area_acres: float | None
    location: GeoPoint
    created_at: datetime
