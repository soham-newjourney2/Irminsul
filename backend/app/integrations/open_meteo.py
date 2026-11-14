"""Open-Meteo forecast client (no key). Fields verified live in M0 (docs/data-sources.md).

Attribution required: "Weather data by Open-Meteo.com" (CC BY 4.0).
"""

from datetime import UTC, datetime
from typing import Any

import httpx

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = ("temperature_2m", "relative_humidity_2m", "precipitation")
DAILY = ("precipitation_sum", "temperature_2m_max", "temperature_2m_min")
TIMEZONE = "Asia/Kolkata"
SOURCE = "open-meteo"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"


class WeatherUnavailable(RuntimeError):
    pass


async def fetch_forecast(
    lat: float,
    lng: float,
    *,
    days: int = 3,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 20,
) -> dict[str, Any]:
    params: dict[str, str | int | float] = {
        "latitude": round(lat, 4),
        "longitude": round(lng, 4),
        "hourly": ",".join(HOURLY),
        "daily": ",".join(DAILY),
        "timezone": TIMEZONE,
        "forecast_days": days,
    }
    owns = client is None
    c = client or httpx.AsyncClient(timeout=timeout_s)
    try:
        r = await c.get(FORECAST_URL, params=params)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise WeatherUnavailable(str(exc)) from exc
    finally:
        if owns:
            await c.aclose()
    for block, keys in (("hourly", HOURLY), ("daily", DAILY)):
        if (
            block not in data
            or "time" not in data[block]
            or any(k not in data[block] for k in keys)
        ):
            raise WeatherUnavailable(f"Unexpected Open-Meteo response: missing {block}")
    data["fetched_at"] = datetime.now(UTC).isoformat()
    return data
