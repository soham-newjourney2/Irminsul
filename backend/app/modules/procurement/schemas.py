from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.app.core.reference import Commodity
from backend.app.core.units import PriceIn, QtyIn, Unit
from backend.app.modules.users.schemas import PartyOut

RequestStatus = Literal["pending", "accepted", "rejected", "countered", "withdrawn"]
OrderStatus = Literal["confirmed", "dispatched", "delivered", "closed", "cancelled"]
DeliveryMode = Literal["pickup", "delivery"]


class PurchaseRequestIn(BaseModel):
    listing_id: str
    qty: QtyIn
    unit: Unit
    price_per_quintal: PriceIn
    delivery_mode: DeliveryMode = "pickup"
    needed_by: date | None = None
    note: str | None = Field(default=None, max_length=500)


class CounterIn(BaseModel):
    qty: QtyIn | None = None
    unit: Unit | None = None
    price_per_quintal: PriceIn
    note: str | None = Field(default=None, max_length=500)


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class HistoryEntry(BaseModel):
    by: Literal["farmer", "distributor", "admin", "system"]
    action: str
    qty_kg: int | None = None
    price_paise_per_quintal: int | None = None
    note: str | None = None
    at: datetime


class PurchaseRequestOut(BaseModel):
    id: str
    listing_id: str
    commodity: Commodity
    variety: str | None
    district: str
    qty_kg: int
    display_unit: Unit
    offered_price_paise_per_quintal: int
    asking_price_paise_per_quintal: int
    delivery_mode: DeliveryMode
    needed_by: date | None
    note: str | None
    status: RequestStatus
    awaiting: Literal["farmer", "distributor"] | None
    history: list[HistoryEntry]
    counterparty: PartyOut | None
    order_id: str | None
    created_at: datetime
    updated_at: datetime


class OrderHistoryEntry(BaseModel):
    status: OrderStatus
    by: Literal["farmer", "distributor", "admin"]
    note: str | None = None
    at: datetime


class OrderOut(BaseModel):
    id: str
    listing_id: str
    request_id: str
    batch_id: str | None
    commodity: Commodity
    variety: str | None
    district: str
    qty_kg: int
    display_unit: Unit
    agreed_price_paise_per_quintal: int
    total_paise: int
    currency: Literal["INR"] = "INR"
    delivery_mode: DeliveryMode
    status: OrderStatus
    history: list[OrderHistoryEntry]
    farmer: PartyOut | None
    distributor: PartyOut | None
    created_at: datetime
    updated_at: datetime
