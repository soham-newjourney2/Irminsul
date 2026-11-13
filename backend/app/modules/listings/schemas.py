from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from backend.app.core.geo import GeoPoint
from backend.app.core.reference import Commodity
from backend.app.core.units import PriceIn, QtyIn, Unit
from backend.app.modules.users.schemas import PartyOut

ListingStatus = Literal[
    "draft", "active", "reserved", "partially_fulfilled", "sold", "expired", "cancelled"
]
OPEN_FOR_REQUESTS: tuple[str, ...] = ("active", "partially_fulfilled")


class ListingIn(BaseModel):
    farm_id: str
    commodity: Commodity
    variety: str | None = Field(default=None, max_length=60)
    grade: str | None = Field(default=None, max_length=30)
    qty: QtyIn
    unit: Unit
    harvest_date: date | None = None
    available_from: date
    available_until: date | None = None
    asking_price_per_quintal: PriceIn
    note: str | None = Field(default=None, max_length=500)
    publish: bool = True

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.available_until and self.available_until < self.available_from:
            raise ValueError("available_until must be on or after available_from")
        if self.harvest_date and self.harvest_date > self.available_from:
            raise ValueError("harvest_date cannot be after available_from")
        return self


class ListingUpdate(BaseModel):
    variety: str | None = Field(default=None, max_length=60)
    grade: str | None = Field(default=None, max_length=30)
    available_until: date | None = None
    asking_price_per_quintal: PriceIn | None = None
    note: str | None = Field(default=None, max_length=500)


class ListingOut(BaseModel):
    id: str
    farmer: PartyOut | None
    farm_id: str
    commodity: Commodity
    variety: str | None
    grade: str | None
    qty_kg: int
    remaining_kg: int
    display_unit: Unit
    harvest_date: date | None
    available_from: date
    available_until: date | None
    asking_price_paise_per_quintal: int
    currency: Literal["INR"] = "INR"
    district: str
    location: GeoPoint
    batch_id: str | None
    status: ListingStatus
    note: str | None
    is_mine: bool
    is_demo: bool
    distance_km: float | None = None
    created_at: datetime
    updated_at: datetime
