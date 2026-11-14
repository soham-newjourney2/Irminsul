"""Crop screening: validated upload → cleaned JPEG in GridFS → ONNX → bounded result.

Upload safety (planning §11): size cap, MIME allow-list, Pillow verify, pixel cap against
decompression bombs, and re-encoding to a plain JPEG (drops EXIF incl. GPS and any
trailing payload) before anything is stored or analysed.
"""

import asyncio
import io
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from fastapi import UploadFile
from gridfs import AsyncGridFSBucket
from PIL import Image, ImageOps, UnidentifiedImageError
from pymongo import DESCENDING
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.ai import inference
from backend.app.core.errors import AppError
from backend.app.core.ratelimit import RateLimiter
from backend.app.core.schemas import parse_object_id
from backend.app.db.client import Doc
from backend.app.modules.batches.service import emit, owned_open_batch
from backend.app.modules.screening.schemas import CandidateOut, ScreeningOut

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 25_000_000
STORED_MAX_EDGE = 1024
ALLOWED_MIME = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
BUCKET = "screening_images"
LIMITATIONS = [
    "possible_condition_not_diagnosis",
    "lab_trained_model",
    "single_leaf_daylight",
    "confirm_with_kvk",
]

screening_limiter = RateLimiter(limit=10, window_s=60)  # per user (planning §8)


def _bucket(db: AsyncDatabase[Doc]) -> AsyncGridFSBucket:
    return AsyncGridFSBucket(db, bucket_name=BUCKET)


async def read_upload(upload: UploadFile) -> bytes:
    if (upload.content_type or "").lower() not in ALLOWED_MIME:
        raise AppError(415, "unsupported_image_type", "Upload a JPEG, PNG or WebP photo")
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError(413, "image_too_large", "Photo must be 2 MB or smaller")
    if not data:
        raise AppError(422, "validation_error", "Empty file")
    return data


def clean_image(data: bytes, declared_mime: str) -> tuple[Image.Image, bytes]:
    """Verify, bound, normalise orientation, downscale, and re-encode as EXIF-free JPEG."""
    try:
        probe = Image.open(io.BytesIO(data))
        fmt = probe.format
        w, h = probe.size
        probe.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
        raise AppError(422, "invalid_image", "This file is not a readable image") from None
    if fmt != ALLOWED_MIME.get(declared_mime.lower()):
        raise AppError(422, "invalid_image", "File content does not match its type")
    if w * h > MAX_PIXELS:
        raise AppError(422, "invalid_image", "Image dimensions are too large")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except (OSError, Image.DecompressionBombError):
        raise AppError(422, "invalid_image", "This file is not a readable image") from None
    img.thumbnail((STORED_MAX_EDGE, STORED_MAX_EDGE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return img, out.getvalue()


def _out(doc: Doc) -> ScreeningOut:
    top = [CandidateOut(**c) for c in doc["top"]]
    key = None
    if doc["status"] == "ok" and top:
        key = f"{doc['crop']}.{top[0].disease}"
    return ScreeningOut(
        id=str(doc["_id"]),
        crop=doc["crop"],
        status=doc["status"],
        reason=doc.get("reason"),
        top=top,
        crop_probability_mass=doc["crop_probability_mass"],
        threshold=doc["threshold"],
        threshold_status=doc["threshold_status"],
        model_version=doc["model_version"],
        batch_id=str(doc["batch_id"]) if doc.get("batch_id") else None,
        guidance_key=key,
        limitations=LIMITATIONS,
        created_at=doc["created_at"],
    )


async def screen(
    db: AsyncDatabase[Doc],
    farmer: Doc,
    crop: str,
    upload: UploadFile,
    batch_id: str | None,
) -> ScreeningOut:
    if not screening_limiter.hit(str(farmer["_id"])):
        raise AppError(429, "rate_limited", "Too many screenings. Try again in a minute")
    try:
        bundle = inference.load_bundle()
    except inference.ModelUnavailable:
        raise AppError(503, "model_unavailable", "Screening is temporarily unavailable") from None
    if crop not in inference.supported_crops(bundle):
        raise AppError(422, "crop_not_supported", "Screening is not available for this crop yet")

    batch = None
    if batch_id:
        batch = await owned_open_batch(db, farmer, parse_object_id(batch_id, "batch"), crop)

    data = await read_upload(upload)
    img, clean_jpeg = await asyncio.to_thread(clean_image, data, upload.content_type or "")
    result = await asyncio.to_thread(inference.run, bundle, img, crop)

    now = datetime.now(UTC)
    file_id = await _bucket(db).upload_from_stream(
        f"screening-{now:%Y%m%dT%H%M%S}.jpg",
        io.BytesIO(clean_jpeg),
        metadata={"user_id": farmer["_id"], "content_type": "image/jpeg"},
    )
    doc: Doc = {
        "schema_version": 1,
        "farmer_id": farmer["_id"],
        "crop": crop,
        "image_file_id": file_id,
        "status": result.status,
        "reason": result.reason,
        "top": [c.__dict__ for c in result.top],
        "crop_probability_mass": result.crop_probability_mass,
        "threshold": result.threshold,
        "threshold_status": result.threshold_status,
        "model_version": result.model_version,
        "batch_id": batch["_id"] if batch else None,
        "is_demo": False,
        "created_at": now,
    }
    doc["_id"] = (await db.crop_screenings.insert_one(doc)).inserted_id
    if batch is not None:
        top = result.top[0]
        payload: dict[str, Any] = {
            "screening_id": str(doc["_id"]),
            "status": result.status,
            "label": top.disease if result.status == "ok" else "unsure",
            "confidence": top.probability,
            "model_version": result.model_version,
        }
        await emit(
            db,
            batch["_id"],
            "screened",
            farmer,
            payload,
            source="user",
            batch_changes={"screening_id": doc["_id"]},
        )
    return _out(doc)


async def list_mine(db: AsyncDatabase[Doc], farmer: Doc, limit: int) -> list[ScreeningOut]:
    rows = (
        await db.crop_screenings.find({"farmer_id": farmer["_id"]})
        .sort("created_at", DESCENDING)
        .to_list(limit)
    )
    return [_out(r) for r in rows]


async def _owned(db: AsyncDatabase[Doc], farmer: Doc, screening_id: ObjectId) -> Doc:
    doc = await db.crop_screenings.find_one({"_id": screening_id, "farmer_id": farmer["_id"]})
    if doc is None:
        raise AppError(404, "not_found", "Screening not found")
    return doc


async def get(db: AsyncDatabase[Doc], farmer: Doc, screening_id: ObjectId) -> ScreeningOut:
    return _out(await _owned(db, farmer, screening_id))


async def image_bytes(db: AsyncDatabase[Doc], farmer: Doc, screening_id: ObjectId) -> bytes:
    doc = await _owned(db, farmer, screening_id)
    stream = await _bucket(db).open_download_stream(doc["image_file_id"])
    return await stream.read()
