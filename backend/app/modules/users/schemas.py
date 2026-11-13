import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from backend.app.db.client import Doc

Role = Literal["farmer", "distributor", "storage_operator", "admin"]
SignupRole = Literal["farmer", "distributor", "storage_operator"]
UserStatus = Literal["active", "pending", "rejected"]
Language = Literal["en", "bn", "hi"]

PENDING_ROLES: frozenset[str] = frozenset({"distributor", "storage_operator"})

_INDIAN_MOBILE = re.compile(r"^[6-9]\d{9}$")


def normalize_phone(raw: str) -> str:
    """Accepts 10-digit Indian mobiles with optional +91 / 91 / 0 prefix → '+91XXXXXXXXXX'."""
    digits = re.sub(r"[\s\-()]", "", raw)
    if digits.startswith("+91"):
        digits = digits[3:]
    elif len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not _INDIAN_MOBILE.fullmatch(digits):
        raise ValueError("Enter a valid 10-digit Indian mobile number")
    return f"+91{digits}"


class OrgOut(BaseModel):
    id: str
    name: str
    kind: str
    status: UserStatus


class UserOut(BaseModel):
    id: str
    phone: str
    name: str
    role: Role
    status: UserStatus
    language: Language
    org: OrgOut | None = None
    created_at: datetime


class UserUpdateIn(BaseModel):
    language: Language


def user_out(user: Doc, org: Doc | None = None) -> UserOut:
    return UserOut(
        id=str(user["_id"]),
        phone=user["phone"],
        name=user["name"],
        role=user["role"],
        status=user["status"],
        language=user.get("language", "en"),
        org=(
            OrgOut(id=str(org["_id"]), name=org["name"], kind=org["kind"], status=org["status"])
            if org
            else None
        ),
        created_at=user["created_at"],
    )


class PartyOut(BaseModel):
    """Counterparty view. `phone` is only filled once contact reveal is allowed."""

    id: str
    name: str
    org_name: str | None = None
    district: str | None = None
    phone: str | None = None
