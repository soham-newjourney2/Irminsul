"""Screening: preprocessing + output mapping with a tiny fixture."""

from typing import Any

import numpy as np
import pytest
from PIL import Image

from backend.app.ai import inference
from backend.app.ai.inference import Bundle, interpret, preprocess, softmax

CFG = {
    "resize_shortest_edge": 8,
    "center_crop": [4, 4],
    "rescale_factor": 1 / 255,
    "mean": [0.5, 0.5, 0.5],
    "std": [0.5, 0.5, 0.5],
}
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
THRESHOLDS = {
    "confidence_threshold": 0.6,
    "confidence_threshold_status": "provisional",
    "crop_mass_min": 0.5,
    "temperature": 1.0,
    "supported_crops": ["potato", "tomato"],
}


class FakeSession:
    def __init__(self, logits: list[float]) -> None:
        self.logits = np.asarray([logits], dtype=np.float32)
        self.seen: dict[str, Any] = {}

    def run(self, output_names: Any, input_feed: Any, run_options: Any = None) -> list[Any]:
        self.seen = input_feed
        return [self.logits]


def _bundle(logits: list[float]) -> Bundle:
    return Bundle(
        session=FakeSession(logits),
        preprocess=CFG,
        classes=CLASSES,
        thresholds=THRESHOLDS,
        manifest={"name": "tiny", "revision": "abcdef1234"},
    )


def test_preprocess_shape_and_normalisation() -> None:
    white = Image.new("RGB", (16, 10), (255, 255, 255))
    x = preprocess(white, CFG)
    assert x.shape == (1, 3, 4, 4)
    assert x.dtype == np.float32
    assert np.allclose(x, 1.0)  # (1 - 0.5) / 0.5
    black = preprocess(Image.new("RGB", (10, 16), (0, 0, 0)), CFG)
    assert np.allclose(black, -1.0)


def test_preprocess_handles_grayscale_and_alpha() -> None:
    assert preprocess(Image.new("L", (9, 9), 128), CFG).shape == (1, 3, 4, 4)
    assert preprocess(Image.new("RGBA", (9, 9), (0, 0, 0, 0)), CFG).shape == (1, 3, 4, 4)


def test_preprocess_centre_crops() -> None:
    img = Image.new("RGB", (16, 8), (0, 0, 0))
    for x in range(4, 12):  # paint the centre band white
        for y in range(8):
            img.putpixel((x, y), (255, 255, 255))
    out = preprocess(img, CFG)
    assert np.allclose(out, 1.0)


def test_softmax_temperature() -> None:
    p = softmax(np.array([2.0, 1.0, 0.0]))
    assert abs(p.sum() - 1) < 1e-9
    sharper = softmax(np.array([2.0, 1.0, 0.0]), temperature=0.5)
    assert sharper[0] > p[0]


def test_confident_result() -> None:
    b = _bundle([0.0, 6.0, 0.0, 0.0])
    r = inference.run(b, Image.new("RGB", (8, 8)), "potato")
    assert r.status == "ok"
    assert r.top[0].disease == "late_blight"
    assert r.top[0].probability > 0.9
    assert [c.disease for c in r.top] == ["late_blight", "early_blight", "healthy"]
    assert r.model_version == "tiny@abcdef1"
    assert b.session.seen["pixel_values"].shape == (1, 3, 4, 4)  # type: ignore[attr-defined]


def test_low_confidence_is_unsure() -> None:
    r = interpret(np.array([0.35, 0.33, 0.30, 0.02]), _bundle([0, 0, 0, 0]), "potato")
    assert (r.status, r.reason) == ("unsure", "low_confidence")


def test_other_crop_photo_is_unsure() -> None:
    # Most probability on a tomato class while the farmer selected potato.
    r = interpret(np.array([0.1, 0.1, 0.1, 0.7]), _bundle([0, 0, 0, 0]), "potato")
    assert (r.status, r.reason) == ("unsure", "not_this_crop")
    assert r.crop_probability_mass == pytest.approx(0.3)


def test_probabilities_not_renormalised_within_crop() -> None:
    r = interpret(np.array([0.05, 0.55, 0.05, 0.35]), _bundle([0, 0, 0, 0]), "potato")
    assert r.top[0].probability == pytest.approx(0.55)
    assert r.status == "unsure"  # 0.55 < 0.6 threshold


def test_unknown_crop_rejected() -> None:
    with pytest.raises(ValueError):
        interpret(np.array([0.25] * 4), _bundle([0, 0, 0, 0]), "rice")


def test_real_model_loads_when_exported() -> None:
    try:
        bundle = inference.load_bundle()
    except inference.ModelUnavailable:
        pytest.skip("model not exported locally")
    assert len(bundle.classes) == 38
    assert {c["crop"] for c in bundle.classes} >= {"potato", "tomato"}
    potato = sorted(c["disease"] for c in bundle.classes if c["crop"] == "potato")
    assert potato == ["early_blight", "healthy", "late_blight"]
    r = inference.run(bundle, Image.new("RGB", (300, 300), (40, 120, 40)), "potato")
    assert r.status in ("ok", "unsure")
    assert 0.0 <= r.crop_probability_mass <= 1.0
