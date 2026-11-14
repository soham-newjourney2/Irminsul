from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.modules.users.schemas import PENDING_ROLES, Language, SignupRole, normalize_email


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=80)
    role: SignupRole
    language: Language = "en"
    org_name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("name", "org_name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if v is not None else None

    @model_validator(mode="after")
    def _org_required(self) -> Self:
        if not self.name:
            raise ValueError("Name is required")
        if self.role in PENDING_ROLES:
            if not self.org_name:
                raise ValueError("Organization or facility name is required for this role")
        else:
            self.org_name = None
        return self


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)
