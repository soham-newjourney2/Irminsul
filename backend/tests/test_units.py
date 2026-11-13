from decimal import Decimal

import pytest

from backend.app.core.units import from_kg, rupees_to_paise, to_kg, total_paise


@pytest.mark.parametrize(
    ("qty", "unit", "kg"),
    [
        ("1", "kg", 1),
        ("2.5", "quintal", 250),
        ("1", "tonne", 1000),
        ("0.125", "tonne", 125),
        ("10.4", "kg", 10),
        ("10.5", "kg", 11),  # half-up
    ],
)
def test_to_kg(qty: str, unit: str, kg: int) -> None:
    assert to_kg(Decimal(qty), unit) == kg


@pytest.mark.parametrize(("qty", "unit"), [("0.4", "kg"), ("10001", "tonne"), ("1", "maund")])
def test_to_kg_rejects(qty: str, unit: str) -> None:
    with pytest.raises(ValueError):
        to_kg(Decimal(qty), unit)


def test_from_kg_round_trip() -> None:
    assert from_kg(250, "quintal") == Decimal("2.5")
    assert from_kg(1500, "tonne") == Decimal("1.5")


def test_money() -> None:
    assert rupees_to_paise(Decimal("1250.50")) == 125050
    # 250 kg at ₹1,200 / quintal = ₹3,000
    assert total_paise(250, 120000) == 300000
    # 1 kg at ₹1,234.55 / quintal = ₹12.3455 → 1235 paise (half-up)
    assert total_paise(1, 123455) == 1235
    with pytest.raises(ValueError):
        rupees_to_paise(Decimal("0"))
