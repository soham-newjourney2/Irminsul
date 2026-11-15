"""Road distance via the public OSRM demo server (shape verified live 2026-11-14).

Fallback when OSRM fails: great-circle (Haversine) x 1.3, always labelled "estimate".
The public server is rate-limited; callers should cache results.
"""

import math
from dataclasses import dataclass
from typing import Literal

import httpx

ROUTE_URL = "https://router.project-osrm.org/route/v1/driving/{lng1},{lat1};{lng2},{lat2}"
ROAD_FACTOR = 1.3
USER_AGENT = "IrminsulHackathon/0.1"


@dataclass(frozen=True)
class Distance:
    km: float
    source: Literal["osrm", "haversine_estimate"]
    duration_min: float | None = None


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def estimate(lat1: float, lng1: float, lat2: float, lng2: float) -> Distance:
    return Distance(
        km=round(haversine_km(lat1, lng1, lat2, lng2) * ROAD_FACTOR, 1), source="haversine_estimate"
    )


async def road_distance(
    lat1: float,
    lng1: float,
    lat2: float,
    lng2: float,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 10,
) -> Distance:
    url = ROUTE_URL.format(lat1=lat1, lng1=lng1, lat2=lat2, lng2=lng2)
    owns = client is None
    c = client or httpx.AsyncClient(timeout=timeout_s, headers={"User-Agent": USER_AGENT})
    try:
        r = await c.get(url, params={"overview": "false", "alternatives": "false"})
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            return estimate(lat1, lng1, lat2, lng2)
        route = data["routes"][0]
        return Distance(
            km=round(float(route["distance"]) / 1000, 1),
            source="osrm",
            duration_min=round(float(route["duration"]) / 60, 0),
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return estimate(lat1, lng1, lat2, lng2)
    finally:
        if owns:
            await c.aclose()
