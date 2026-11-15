"""Quantities are stored as integer kg; money as integer paise."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import Field

Unit = Literal["kg", "quintal", "tonne"]
KG_PER_UNIT: dict[str, int] = {"kg": 1, "quintal": 100, "tonne": 1000}

MAX_KG = 10_000_000  # 10,000 tonnes — sanity cap per record
MAX_PRICE_RUPEES_PER_QUINTAL = Decimal("1000000")

QtyIn = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=3)]
PriceIn = Annotated[Decimal, Field(gt=0, max_digits=10, decimal_places=2)]


def to_kg(qty: Decimal, unit: str) -> int:
    """Convert to whole kg (half-up). Raises ValueError outside 1 kg … MAX_KG."""
    if unit not in KG_PER_UNIT:
        raise ValueError(f"Unknown unit: {unit}")
    kg = int((qty * KG_PER_UNIT[unit]).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if kg < 1:
        raise ValueError("Quantity must be at least 1 kg")
    if kg > MAX_KG:
        raise ValueError("Quantity is too large")
    return kg


def from_kg(kg: int, unit: str) -> Decimal:
    return (Decimal(kg) / KG_PER_UNIT[unit]).normalize()


def rupees_to_paise(rupees: Decimal) -> int:
    if rupees <= 0 or rupees > MAX_PRICE_RUPEES_PER_QUINTAL:
        raise ValueError("Price out of range")
    return int((rupees * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def total_paise(qty_kg: int, price_paise_per_quintal: int) -> int:
    """qty (kg) * price (paise / 100 kg), rounded half-up to whole paise."""
    return (qty_kg * price_paise_per_quintal + 50) // 100
