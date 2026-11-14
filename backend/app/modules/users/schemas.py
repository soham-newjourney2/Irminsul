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

# Practical address check (no extra dependency): local@domain.tld, lower-cased. Local part is
# limited to a-z 0-9 . _ % + - so a stored address can never inject mailto: parameters (? & =).
_EMAIL = re.compile(
    r"^[a-z0-9._%+-]{1,64}@"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)


def normalize_email(raw: str) -> str:
    """Trim + lower-case; reject anything that is not a plausible single address."""
    v = raw.strip().lower()
    if len(v) > 254 or ".." in v or v.startswith(".") or ".@" in v or not _EMAIL.fullmatch(v):
        raise ValueError("Enter a valid email address")
    return v


class OrgOut(BaseModel):
    id: str
    name: str
    kind: str
    status: UserStatus


class UserOut(BaseModel):
    id: str
    email: str
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
        email=user["email"],
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
    """Counterparty view. `email` is only filled once contact reveal is allowed."""

    id: str
    name: str
    org_name: str | None = None
    district: str | None = None
    email: str | None = None
