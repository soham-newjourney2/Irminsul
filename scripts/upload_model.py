"""Upload the locally exported screening model to MongoDB GridFS and write the lock file.

Usage (once, locally, after scripts/export_model.py):  uv run python -I scripts/upload_model.py
- Files go to GridFS bucket "model_files" (idempotent: identical files are not re-uploaded).
- ai/model_cards/plantvillage-mobilenetv2.lock.json (committed) pins every file's SHA-256;
  scripts/download_models.py refuses anything that does not match it.
"""

import asyncio
import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gridfs import AsyncGridFSBucket  # noqa: E402

from backend.app.ai.inference import MODELS_ROOT  # noqa: E402
from backend.app.config import get_settings  # noqa: E402
from backend.app.db.client import mongo  # noqa: E402

FILES = ("model.onnx", "preprocess.json", "class_map.json", "thresholds.json", "manifest.json")
LOCK = ROOT / "ai" / "model_cards" / "plantvillage-mobilenetv2.lock.json"
BUCKET = "model_files"


async def main() -> int:
    dirs = sorted(
        (d for d in MODELS_ROOT.iterdir() if (d / "manifest.json").is_file()), reverse=True
    )
    if not dirs:
        print("No exported model found; run scripts/export_model.py first", file=sys.stderr)
        return 1
    model_dir = dirs[0]
    manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
    await mongo.connect(get_settings())
    if mongo.db is None:
        print("MONGODB_URI not set", file=sys.stderr)
        return 1
    bucket = AsyncGridFSBucket(mongo.db, bucket_name=BUCKET)
    lock = {
        "name": manifest["name"],
        "revision": manifest["revision"],
        "dir": model_dir.name,
        "bucket": BUCKET,
        "database": get_settings().mongodb_db,
        "files": {},
    }
    try:
        for name in FILES:
            data = (model_dir / name).read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            lock["files"][name] = digest
            existing = await mongo.db[f"{BUCKET}.files"].find_one(
                {"metadata.sha256": digest, "filename": name}
            )
            if existing:
                print(f"  {name}: already uploaded")
                continue
            await bucket.upload_from_stream(
                name,
                io.BytesIO(data),
                metadata={
                    "sha256": digest,
                    "model": manifest["name"],
                    "revision": manifest["revision"],
                },
            )
            print(f"  {name}: uploaded ({len(data)} bytes)")
    finally:
        await mongo.close()
    LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(f"Lock file written: {LOCK.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
