"""Create or promote the admin account (admins are never self-registered).

Usage: uv run python scripts/create_admin.py --phone 98XXXXXXXX --name "Admin"
Password comes from ADMIN_PASSWORD or an interactive prompt; it is never hard-coded.
"""

import argparse
import asyncio
import getpass
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.config import get_settings
from backend.app.core.security import hash_password
from backend.app.db.client import mongo
from backend.app.db.indexes import ensure_indexes
from backend.app.modules.users.schemas import normalize_phone


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--name", default="Admin")
    args = parser.parse_args()

    phone = normalize_phone(args.phone)
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters", file=sys.stderr)
        return 1

    settings = get_settings()
    await mongo.connect(settings)
    if mongo.db is None:
        print("MONGODB_URI not set", file=sys.stderr)
        return 1
    try:
        await ensure_indexes(mongo.db)
        now = datetime.now(UTC)
        await mongo.db.users.update_one(
            {"phone": phone},
            {
                "$set": {
                    "name": args.name,
                    "role": "admin",
                    "status": "active",
                    "password_hash": await hash_password(password),
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "schema_version": 1,
                    "phone": phone,
                    "language": "en",
                    "org_id": None,
                    "created_at": now,
                },
            },
            upsert=True,
        )
        print(f"Admin ready: {phone}")
    finally:
        await mongo.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
