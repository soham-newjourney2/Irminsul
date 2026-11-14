"""Fetch the screening model from GridFS at build time and verify it against the committed lock.

Usage (Render build step):  uv run python -I scripts/download_models.py
Exits non-zero — failing the build — if any file is missing or its SHA-256 differs from
ai/model_cards/plantvillage-mobilenetv2.lock.json. Skips files already present and valid.
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gridfs import AsyncGridFSBucket  # noqa: E402

from backend.app.ai.inference import MODELS_ROOT  # noqa: E402
from backend.app.config import get_settings  # noqa: E402
from backend.app.db.client import mongo  # noqa: E402

LOCK = ROOT / "ai" / "model_cards" / "plantvillage-mobilenetv2.lock.json"


async def main() -> int:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    target = MODELS_ROOT / lock["dir"]
    target.mkdir(parents=True, exist_ok=True)
    todo = {
        name: digest
        for name, digest in lock["files"].items()
        if not (target / name).is_file()
        or hashlib.sha256((target / name).read_bytes()).hexdigest() != digest
    }
    if not todo:
        print("Model files present and verified.")
        return 0
    # The model lives in the database recorded in the lock (may differ from the app database).
    await mongo.connect(get_settings(), db_name=lock.get("database"))
    if mongo.db is None:
        print("MONGODB_URI not set", file=sys.stderr)
        return 1
    bucket = AsyncGridFSBucket(mongo.db, bucket_name=lock["bucket"])
    try:
        for name, digest in todo.items():
            row = await mongo.db[f"{lock['bucket']}.files"].find_one(
                {"filename": name, "metadata.sha256": digest}
            )
            if row is None:
                print(f"Missing in GridFS: {name} ({digest[:12]}…)", file=sys.stderr)
                return 1
            stream = await bucket.open_download_stream(row["_id"])
            data = await stream.read()
            if hashlib.sha256(data).hexdigest() != digest:
                print(f"Checksum mismatch for {name}; refusing to install it", file=sys.stderr)
                return 1
            (target / name).write_bytes(data)
            print(f"  {name}: installed ({len(data)} bytes, verified)")
    finally:
        await mongo.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
