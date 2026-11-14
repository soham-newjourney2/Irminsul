from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AlertStatus = Literal["open", "acknowledged", "resolved"]
ObsSource = Literal["manual", "simulated"]


class ObservationIn(BaseModel):
    zone_id: str
    observed_at: datetime | None = None  # default: now (server time, UTC)
    temp: float | None = Field(default=None, ge=-60, le=150)
    temp_unit: Literal["C", "F"] = "C"
    rh_pct: float | None = Field(default=None, ge=0, le=100)
    note: str | None = Field(default=None, max_length=300)


class ObservationOut(BaseModel):
    id: str
    zone_id: str
    observed_at: datetime
    temp_c: float | None
    rh_pct: float | None
    source: ObsSource
    note: str | None


class AlertOut(BaseModel):
    id: str
    facility_id: str
    facility_name: str | None
    zone_id: str
    zone_name: str | None
    kind: str
    severity: str
    status: AlertStatus
    metric: str | None
    threshold: float | None
    peak: float | None
    started_at: datetime
    latest_at: datetime
    duration_min: float
    condition_active: bool
    cleared_at: datetime | None
    profile: dict[str, Any] | None
    details: dict[str, Any]
    simulated: bool
    history: list[dict[str, Any]]
    inspection: dict[str, Any] | None
    created_at: datetime


class AckIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)


class ResolveIn(BaseModel):
    findings: str = Field(min_length=5, max_length=1000)
    corrective_action: str = Field(min_length=5, max_length=1000)
    inspected_at: datetime | None = None


class ObservationsOut(BaseModel):
    zone: dict[str, Any]
    profile: dict[str, Any] | None
    readings: list[ObservationOut]
    last_reading_at: datetime | None


class InjectIn(BaseModel):
    zone_id: str
    kind: Literal["temp_high", "temp_low", "rh_high", "rh_low", "implausible"] = "temp_high"
    minutes: int = Field(default=45, ge=5, le=360)
    magnitude: float = Field(default=2.5, gt=0, le=20)


class SimulatorIn(BaseModel):
    zone_id: str
    interval_s: int = Field(default=60, ge=5, le=900)
