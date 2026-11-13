"""Shared response envelope and id helpers."""

from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BaseModel, Field

from backend.app.core.errors import AppError


class Envelope[T](BaseModel):
    data: T
    meta: dict[str, Any] = Field(default_factory=dict)


def parse_object_id(value: str, what: str = "resource") -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise AppError(404, "not_found", f"{what.capitalize()} not found") from None
