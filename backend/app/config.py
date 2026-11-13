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

    frontend_dir: Path = REPO_ROOT / "frontend"


@lru_cache
def get_settings() -> Settings:
    return Settings()
