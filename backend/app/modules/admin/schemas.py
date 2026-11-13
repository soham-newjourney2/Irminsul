from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RejectIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class AuditLogOut(BaseModel):
    id: str
    actor_id: str
    action: str
    target_type: str
    target_id: str
    details: dict[str, Any]
    created_at: datetime
