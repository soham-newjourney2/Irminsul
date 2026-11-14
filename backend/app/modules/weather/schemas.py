from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from backend.app.core.geo import GeoPoint


class DailyOut(BaseModel):
    date: str
    precipitation_mm: float | None
    temp_max_c: float | None
    temp_min_c: float | None


class HourlyOut(BaseModel):
    time: str
    temp_c: float | None
    rh_pct: float | None
    precipitation_mm: float | None


class WeatherOut(BaseModel):
    location: GeoPoint
    timezone: str
    kind: Literal["forecast"] = "forecast"
    daily: list[DailyOut]
    next_hours: list[HourlyOut]
    source: str
    attribution: str
    fetched_at: datetime
    cached: bool
    stale: bool


class AdvisoryOut(BaseModel):
    rule_id: str
    kind: str
    severity: str
    crop: str | None
    disease: str | None
    label: str | None
    evidence: dict[str, Any]
    window_start: str
    window_end: str
    source: dict[str, Any]
    verified: bool
    assumptions: list[str]
    guidance_key: str | None


class GuidanceOut(BaseModel):
    key: str
    entry: dict[str, Any]
    review_status: str
    translation_status: str
    policy: str
