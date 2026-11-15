"""AGMARKNET row normalisation: market names, crops, ₹/quintal → integer paise."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CROP_OF_COMMODITY = {
    "potato": "potato",
    "tomato": "tomato",
    "rice": "rice",
    "paddy (dhan)(common)": "rice",
    "paddy (common)": "rice",
    "jute": "jute",
}


def clean_market(name: str) -> str:
    """'Bishnupur (Bankura) APMC' → 'Bishnupur' (same rule as scripts/data/geocode_markets.py)."""
    n = re.sub(r"\bAPMC\b|\(.*?\)", " ", name, flags=re.I)
    n = n.replace("/", " ")
    return re.sub(r"\s+", " ", n).strip()


def market_key(district: str, market: str) -> str:
    return f"{district.strip()}|{clean_market(market)}"


def crop_of(commodity: str) -> str | None:
    return CROP_OF_COMMODITY.get(commodity.strip().lower())


def rupees_per_quintal_to_paise(value: str | float | int | None) -> int | None:
    """AGMARKNET prices are ₹/quintal. Returns None for missing, zero, or invalid values."""
    if value is None or value == "":
        return None
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return None
    if d <= 0 or d > Decimal("10000000"):
        return None
    return int((d * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def normalise_row(row: dict[str, str]) -> dict[str, object] | None:
    """Snapshot CSV row → price observation fields, or None when the row is unusable."""
    crop = crop_of(row.get("Commodity", ""))
    if crop is None:
        return None
    lo = rupees_per_quintal_to_paise(row.get("Min_Price"))
    hi = rupees_per_quintal_to_paise(row.get("Max_Price"))
    modal = rupees_per_quintal_to_paise(row.get("Modal_Price"))
    if modal is None or lo is None or hi is None or lo > hi or not (lo <= modal <= hi):
        return None
    date = (row.get("Arrival_Date") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return None
    district = row["District"].strip()
    return {
        "market_key": market_key(district, row["Market"]),
        "district": district,
        "market": clean_market(row["Market"]),
        "market_raw": row["Market"].strip(),
        "commodity": row["Commodity"].strip(),
        "crop": crop,
        "variety": (row.get("Variety") or "").strip() or None,
        "grade": (row.get("Grade") or "").strip() or None,
        "arrival_date": date,
        "min_price_paise_per_quintal": lo,
        "max_price_paise_per_quintal": hi,
        "modal_price_paise_per_quintal": modal,
    }
