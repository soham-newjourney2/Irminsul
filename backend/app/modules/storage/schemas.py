from datetime import UTC, date, datetime, timedelta
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.core.geo import GeoPoint
from backend.app.core.reference import Commodity, validate_district
from backend.app.core.units import QtyIn, Unit
from backend.app.modules.users.schemas import PartyOut, normalize_phone

FacilityStatus = Literal["active", "inactive"]
BookingStatus = Literal[
    "requested", "accepted", "rejected", "changes_requested", "checked_in", "released", "cancelled"
]
ZoneKind = Literal["cold", "ambient"]
MAX_BOOKING_DAYS = 365


class FacilityIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    district: str
    address: str | None = Field(default=None, max_length=300)
    location: GeoPoint
    commodities: list[Commodity] = Field(min_length=1, max_length=4)
    capacity: QtyIn
    capacity_unit: Unit = "tonne"
    contact_phone: str

    @field_validator("district")
    @classmethod
    def _district(cls, v: str) -> str:
        return validate_district(v)

    @field_validator("contact_phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)

    @field_validator("commodities")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


class FacilityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    address: str | None = Field(default=None, max_length=300)
    commodities: list[Commodity] | None = Field(default=None, min_length=1, max_length=4)
    capacity: QtyIn | None = None
    capacity_unit: Unit = "tonne"
    status: FacilityStatus | None = None
    contact_phone: str | None = None

    @field_validator("contact_phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v is not None else None


class FacilityOut(BaseModel):
    id: str
    org_name: str | None
    name: str
    district: str
    address: str | None
    location: GeoPoint
    commodities: list[Commodity]
    capacity_kg: int
    reserved_kg: int
    occupied_kg: int
    free_kg: int
    status: FacilityStatus
    contact_phone: str | None  # only for the operator's own facilities
    is_mine: bool
    is_demo: bool
    distance_km: float | None = None
    created_at: datetime


class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: ZoneKind = "cold"
    commodity: Commodity | None = None
    capacity: QtyIn | None = None
    capacity_unit: Unit = "tonne"


class ZoneOut(BaseModel):
    id: str
    facility_id: str
    name: str
    kind: ZoneKind
    commodity: Commodity | None
    capacity_kg: int | None
    created_at: datetime


def _today() -> date:
    return datetime.now(UTC).date()


class _Dates(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _check_dates(self) -> Self:
        if self.start_date < _today() - timedelta(days=1):
            raise ValueError("start_date cannot be in the past")
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if (self.end_date - self.start_date).days > MAX_BOOKING_DAYS:
            raise ValueError(f"Bookings can be at most {MAX_BOOKING_DAYS} days")
        return self


class BookingIn(_Dates):
    facility_id: str
    commodity: Commodity
    qty: QtyIn
    unit: Unit
    listing_id: str | None = None
    batch_id: str | None = None
    note: str | None = Field(default=None, max_length=500)


class ResubmitIn(_Dates):
    qty: QtyIn
    unit: Unit
    note: str | None = Field(default=None, max_length=500)


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class CheckInIn(BaseModel):
    zone_id: str | None = None
    note: str | None = Field(default=None, max_length=500)


class BookingHistoryEntry(BaseModel):
    status: BookingStatus
    by: Literal["farmer", "storage_operator"]
    note: str | None = None
    at: datetime


class BookingFacility(BaseModel):
    id: str
    name: str
    district: str
    location: GeoPoint
    org_name: str | None
    contact_phone: str | None  # revealed once accepted


class BookingOut(BaseModel):
    id: str
    facility: BookingFacility
    farmer: PartyOut | None
    commodity: Commodity
    qty_kg: int
    display_unit: Unit
    start_date: date
    end_date: date
    listing_id: str | None
    batch_id: str | None
    note: str | None
    status: BookingStatus
    zone_id: str | None
    zone_name: str | None
    history: list[BookingHistoryEntry]
    created_at: datetime
    updated_at: datetime
