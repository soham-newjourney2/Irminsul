from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from backend.app.core.reference import Commodity

ScreeningStatus = Literal["ok", "unsure"]


class CandidateOut(BaseModel):
    disease: str
    label: str
    probability: float
    healthy: bool


class ScreeningOut(BaseModel):
    id: str
    crop: Commodity
    status: ScreeningStatus
    reason: Literal["low_confidence", "not_this_crop"] | None
    top: list[CandidateOut]
    crop_probability_mass: float
    threshold: float
    threshold_status: str
    model_version: str
    batch_id: str | None
    guidance_key: str | None  # "<crop>.<disease>" when a sourced guidance entry may apply
    limitations: list[str]
    created_at: datetime
