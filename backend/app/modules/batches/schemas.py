from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.core.geo import GeoPoint
from backend.app.core.reference import Commodity
from backend.app.core.units import QtyIn, Unit

BatchStatus = Literal["active", "in_storage", "in_transit", "delivered", "split"]
CustodianType = Literal["farmer", "facility", "distributor"]
EventType = Literal[
    "created",
    "screened",
    "listed",
    "request_accepted",
    "booking_confirmed",
    "checked_in",
    "released",
    "observation_summary",
    "split",
    "dispatched",
    "delivered",
    "relocated",
    "inspection",
    "exception",
    "correction",
]


class BatchIn(BaseModel):
    farm_id: str
    commodity: Commodity
    variety: str | None = Field(default=None, max_length=60)
    harvest_date: date
    qty: QtyIn
    unit: Unit


class SplitIn(BaseModel):
    parts: list[QtyIn] = Field(min_length=2, max_length=10)
    unit: Unit


class CorrectionIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)
    corrected: dict[str, Any] = Field(default_factory=dict)


class Custodian(BaseModel):
    type: CustodianType
    id: str
    name: str | None = None


class EventOut(BaseModel):
    seq: int
    type: EventType
    actor_role: str | None
    event_time: datetime
    received_at: datetime
    source: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str


class VerifyOut(BaseModel):
    valid: bool
    events: int
    head_hash: str
    first_invalid_seq: int | None
    reason: str | None
    checked_at: datetime


class LineageOut(BaseModel):
    id: str
    batch_code: str
    qty_kg: int


class BatchOut(BaseModel):
    id: str
    batch_code: str
    commodity: Commodity
    variety: str | None
    harvest_date: date
    district: str
    harvest_location: GeoPoint
    qty_kg: int
    display_unit: Unit
    status: BatchStatus
    custodian: Custodian
    is_mine: bool
    is_demo: bool
    parent: LineageOut | None
    children: list[LineageOut]
    head_seq: int
    created_at: datetime


class BatchDetailOut(BatchOut):
    events: list[EventOut]


class QrOut(BaseModel):
    token: str
    url: str


class PublicEventOut(BaseModel):
    seq: int
    type: EventType
    event_time: datetime
    details: dict[str, Any]


class PublicBatchOut(BaseModel):
    """Public QR view: no names, phones, or exact coordinates (planning §4.2, §11)."""

    batch_code: str
    commodity: Commodity
    variety: str | None
    district: str
    harvest_month: str
    qty_kg: int
    status: BatchStatus
    events: list[PublicEventOut]
    chain: VerifyOut
    is_demo: bool
