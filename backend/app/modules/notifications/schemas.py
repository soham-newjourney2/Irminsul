from datetime import datetime
from typing import Any

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: str
    kind: str
    params: dict[str, Any]
    link: str | None
    read: bool
    created_at: datetime


class MarkReadIn(BaseModel):
    ids: list[str] | None = None  # None → mark all read
