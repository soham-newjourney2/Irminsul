"""Reference data (planning §0): supported crops and West Bengal districts."""

from typing import Literal

Commodity = Literal["potato", "tomato", "rice", "jute"]
COMMODITIES: tuple[str, ...] = ("potato", "tomato", "rice", "jute")

# 23 districts of West Bengal.
WB_DISTRICTS: tuple[str, ...] = (
    "Alipurduar",
    "Bankura",
    "Birbhum",
    "Cooch Behar",
    "Dakshin Dinajpur",
    "Darjeeling",
    "Hooghly",
    "Howrah",
    "Jalpaiguri",
    "Jhargram",
    "Kalimpong",
    "Kolkata",
    "Malda",
    "Murshidabad",
    "Nadia",
    "North 24 Parganas",
    "Paschim Bardhaman",
    "Paschim Medinipur",
    "Purba Bardhaman",
    "Purba Medinipur",
    "Purulia",
    "South 24 Parganas",
    "Uttar Dinajpur",
)


def validate_district(value: str) -> str:
    v = value.strip()
    for d in WB_DISTRICTS:
        if d.lower() == v.lower():
            return d
    raise ValueError("Unknown West Bengal district")
