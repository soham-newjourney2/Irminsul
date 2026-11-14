"""Screening API: upload validation, bounded results, ownership, rate limit, batch event."""

import io
from typing import Any

import httpx
import numpy as np
import pytest
from PIL import Image

from backend.app.ai import inference
from backend.app.ai.inference import Bundle
from backend.app.modules.screening import service
from backend.tests.conftest import UserFactory

pytestmark = pytest.mark.usefixtures("test_db")

CLASSES = [
    {
        "index": 0,
        "label": "Potato___Early_blight",
        "crop": "potato",
        "disease": "early_blight",
        "healthy": False,
    },
    {
        "index": 1,
        "label": "Potato___Late_blight",
        "crop": "potato",
        "disease": "late_blight",
        "healthy": False,
    },
    {
        "index": 2,
        "label": "Potato___healthy",
        "crop": "potato",
        "disease": "healthy",
        "healthy": True,
    },
    {
        "index": 3,
        "label": "Tomato___healthy",
        "crop": "tomato",
        "disease": "healthy",
        "healthy": True,
    },
]


class FakeSession:
    def __init__(self) -> None:
        self.logits = np.array([[0.0, 6.0, 0.0, 0.0]], dtype=np.float32)

    def run(self, output_names: Any, input_feed: Any, run_options: Any = None) -> list[Any]:
        return [self.logits]


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    session = FakeSession()
    bundle = Bundle(
        session=session,
        preprocess={
            "resize_shortest_edge": 8,
            "center_crop": [4, 4],
            "rescale_factor": 1 / 255,
            "mean": [0.5] * 3,
            "std": [0.5] * 3,
        },
        classes=CLASSES,
        thresholds={
            "confidence_threshold": 0.6,
            "confidence_threshold_status": "provisional",
            "crop_mass_min": 0.5,
            "temperature": 1.0,
            "supported_crops": ["potato", "tomato"],
        },
        manifest={"name": "tiny", "revision": "abcdef1234"},
    )
    monkeypatch.setattr(inference, "load_bundle", lambda: bundle)
    return session


def _png(size: tuple[int, int] = (64, 48), exif_gps: bool = False) -> bytes:
    img = Image.new("RGB", size, (60, 140, 60))
    buf = io.BytesIO()
    if exif_gps:
        exif = Image.Exif()
        exif[0x8825] = {2: (22.0, 54.0, 0.0)}  # GPSInfo latitude
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format="PNG")
    return buf.getvalue()


async def _upload(
    c: httpx.AsyncClient, data: bytes, mime: str = "image/png", crop: str = "potato", **form: str
) -> httpx.Response:
    return await c.post(
        "/api/v1/crop-screenings",
        data={"crop": crop, **form},
        files={"image": ("leaf.png", data, mime)},
    )


async def test_confident_screening_stored_and_cleaned(
    make_user: UserFactory, fake_model: FakeSession
) -> None:
    farmer, _ = await make_user("farmer")
    r = await _upload(farmer, _png(exif_gps=True), mime="image/jpeg")
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    assert d["status"] == "ok"
    assert d["top"][0]["disease"] == "late_blight"
    assert d["guidance_key"] == "potato.late_blight"
    assert d["model_version"] == "tiny@abcdef1"
    assert d["threshold_status"] == "provisional"
    assert "possible_condition_not_diagnosis" in d["limitations"]

    img = await farmer.get(f"/api/v1/crop-screenings/{d['id']}/image")
    assert img.headers["content-type"] == "image/jpeg"
    stored = Image.open(io.BytesIO(img.content))
    assert stored.format == "JPEG"
    assert 0x8825 not in stored.getexif()  # GPS stripped
    assert len((await farmer.get("/api/v1/crop-screenings")).json()["data"]) == 1


async def test_unsure_has_no_guidance(make_user: UserFactory, fake_model: FakeSession) -> None:
    fake_model.logits = np.array([[0.3, 0.2, 0.1, 0.0]], dtype=np.float32)
    farmer, _ = await make_user("farmer")
    d = (await _upload(farmer, _png())).json()["data"]
    assert d["status"] == "unsure"
    assert d["reason"] == "low_confidence"
    assert d["guidance_key"] is None


@pytest.mark.parametrize(
    ("data", "mime", "code"),
    [
        (b"not an image at all", "image/png", 422),
        (_png(), "application/pdf", 415),
        (_png(), "image/webp", 422),  # declared WebP, content PNG
        (b"", "image/png", 422),
    ],
)
async def test_upload_validation(
    make_user: UserFactory, fake_model: FakeSession, data: bytes, mime: str, code: int
) -> None:
    farmer, _ = await make_user("farmer")
    assert (await _upload(farmer, data, mime=mime)).status_code == code


async def test_oversized_upload_rejected(make_user: UserFactory, fake_model: FakeSession) -> None:
    farmer, _ = await make_user("farmer")
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (2 * 1024 * 1024 + 10)
    assert (await _upload(farmer, big)).status_code == 413


async def test_unsupported_crops(make_user: UserFactory, fake_model: FakeSession) -> None:
    farmer, _ = await make_user("farmer")
    for crop in ("rice", "jute"):
        r = await _upload(farmer, _png(), crop=crop)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "crop_not_supported"


async def test_only_farmers_and_only_owner(make_user: UserFactory, fake_model: FakeSession) -> None:
    farmer, _ = await make_user("farmer")
    other, _ = await make_user("farmer")
    dist, _ = await make_user("distributor")
    assert (await _upload(dist, _png())).status_code == 403
    sid = (await _upload(farmer, _png())).json()["data"]["id"]
    assert (await other.get(f"/api/v1/crop-screenings/{sid}")).status_code == 404
    assert (await other.get(f"/api/v1/crop-screenings/{sid}/image")).status_code == 404


async def test_rate_limited_per_user(
    make_user: UserFactory, fake_model: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app.core.ratelimit import RateLimiter

    monkeypatch.setattr(service, "screening_limiter", RateLimiter(limit=2, window_s=60))
    farmer, _ = await make_user("farmer")
    codes = [(await _upload(farmer, _png())).status_code for _ in range(3)]
    assert codes == [201, 201, 429]


async def test_batch_link_emits_screened_event(
    make_user: UserFactory, fake_model: FakeSession
) -> None:
    farmer, _ = await make_user("farmer")
    farm = await farmer.post(
        "/api/v1/farms",
        json={"name": "P", "district": "Hooghly", "location": {"lat": 22.9, "lng": 88.39}},
    )
    batch = await farmer.post(
        "/api/v1/batches",
        json={
            "farm_id": farm.json()["data"]["id"],
            "commodity": "potato",
            "harvest_date": "2026-11-01",
            "qty": "1",
            "unit": "quintal",
        },
    )
    bid = batch.json()["data"]["id"]
    r = await _upload(farmer, _png(), batch_id=bid)
    assert r.json()["data"]["batch_id"] == bid
    detail = (await farmer.get(f"/api/v1/batches/{bid}")).json()["data"]
    ev = detail["events"][-1]
    assert ev["type"] == "screened"
    assert ev["payload"]["label"] == "late_blight"
    assert (await farmer.get(f"/api/v1/batches/{bid}/verify")).json()["data"]["valid"] is True
