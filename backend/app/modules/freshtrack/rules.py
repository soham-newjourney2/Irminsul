"""Storage rules (data/storage_rules.json): cited bands per profile + alerting defaults."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.config import REPO_ROOT

RULES_PATH = REPO_ROOT / "data" / "storage_rules.json"


@lru_cache(maxsize=1)
def load(path: Path = RULES_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def defaults() -> dict[str, Any]:
    return load()["defaults"]


def profile(profile_id: str | None) -> dict[str, Any] | None:
    if profile_id is None:
        return None
    p = load()["profiles"].get(profile_id)
    return {"id": profile_id, **p} if p else None


def profile_for(commodity: str | None, explicit: str | None = None) -> dict[str, Any] | None:
    if explicit:
        return profile(explicit)
    if commodity is None:
        return None
    return profile(load()["commodity_defaults"].get(commodity))


def profiles_for_commodity(commodity: str) -> list[str]:
    return [k for k, v in load()["profiles"].items() if v["commodity"] == commodity]
