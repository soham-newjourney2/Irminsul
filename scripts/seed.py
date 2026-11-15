"""Seed the demo data: fictional, clearly labelled records for trying Irminsul end to end.

Usage: uv run python -I scripts/seed.py
- Every demo account uses SEED_DEMO_PASSWORD (8+ characters, never printed or hard-coded).
- Two stages, demo-story-v1 and demo-story-v2, each recorded in `seed_runs` so it runs once.
- Built through the real services, so hash chains, capacities and bookings are genuine.
  Everything is marked is_demo; mandi prices, weather and routes are never faked.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import get_settings
from backend.app.db.client import mongo
from scripts.demo import more, story

STAGES = ((story.MARKER, story.seed), (more.MARKER, more.seed_more))


async def main() -> int:
    settings = get_settings()
    secret = settings.seed_demo_password
    if secret is None or len(secret.get_secret_value()) < 8:
        print("Set SEED_DEMO_PASSWORD (8+ characters) in .env first.", file=sys.stderr)
        return 1
    await mongo.connect(settings)
    if mongo.db is None:
        print("MONGODB_URI not set", file=sys.stderr)
        return 1
    try:
        for marker, stage in STAGES:
            if await mongo.db.seed_runs.find_one({"name": marker}):
                print(f"{marker}: already seeded")
            else:
                print(f"{marker}:", await stage(mongo.db, secret.get_secret_value()))
        print("Demo accounts: see the README. Password: SEED_DEMO_PASSWORD from your .env")
    finally:
        await mongo.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
