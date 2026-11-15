"""Net realization per market, integer paise throughout.

net = qty x modal price - transport (road km x rate/km/quintal x quintals)
      - fees (% of gross)
Every input is returned with the result so the UI can show all assumptions.
"""

from dataclasses import dataclass

from backend.app.core.units import total_paise


@dataclass(frozen=True)
class NetRealization:
    qty_kg: int
    modal_price_paise_per_quintal: int
    distance_km: float
    distance_source: str
    transport_rate_paise_per_km_per_quintal: int
    fees_pct: float
    gross_paise: int
    transport_paise: int
    fees_paise: int
    net_paise: int
    beyond_practical_distance: bool
    practical_distance_km: float


def _round_half_up(x: float) -> int:
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def compute(
    *,
    qty_kg: int,
    modal_price_paise_per_quintal: int,
    distance_km: float,
    distance_source: str,
    transport_rate_paise_per_km_per_quintal: int,
    fees_pct: float,
    practical_distance_km: float,
) -> NetRealization:
    if qty_kg <= 0 or modal_price_paise_per_quintal <= 0:
        raise ValueError("Quantity and price must be positive")
    if distance_km < 0 or transport_rate_paise_per_km_per_quintal < 0:
        raise ValueError("Distance and transport rate cannot be negative")
    if not 0 <= fees_pct <= 100:
        raise ValueError("Fees must be between 0 and 100 %")
    gross = total_paise(qty_kg, modal_price_paise_per_quintal)
    transport = _round_half_up(distance_km * transport_rate_paise_per_km_per_quintal * qty_kg / 100)
    fees = _round_half_up(gross * fees_pct / 100)
    return NetRealization(
        qty_kg=qty_kg,
        modal_price_paise_per_quintal=modal_price_paise_per_quintal,
        distance_km=distance_km,
        distance_source=distance_source,
        transport_rate_paise_per_km_per_quintal=transport_rate_paise_per_km_per_quintal,
        fees_pct=fees_pct,
        gross_paise=gross,
        transport_paise=transport,
        fees_paise=fees,
        net_paise=gross - transport - fees,
        beyond_practical_distance=distance_km > practical_distance_km,
        practical_distance_km=practical_distance_km,
    )
