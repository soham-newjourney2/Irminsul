"""Application settings loaded from environment / `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    environment: Literal["development", "production", "test"] = "development"
    mongodb_uri: SecretStr | None = None
    mongodb_db: str = "irminsul"
    mongodb_test_db: str = "irminsul_test"
    mongodb_timeout_ms: int = 5000

    jwt_secret: SecretStr | None = None
    session_cookie_name: str = "irminsul_session"
    session_ttl_hours: int = 12

    public_base_url: str | None = None  # used in QR codes; falls back to request URL

    data_gov_in_api_key: SecretStr | None = None
    http_timeout_s: float = 20.0

    frontend_dir: Path = REPO_ROOT / "frontend"

    @property
    def cookie_secure(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
