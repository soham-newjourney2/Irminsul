"""Stable screening interface (planning §6): ONNX model + preprocessing + class map + thresholds.

Results are bounded: probabilities are reported as they are (temperature-calibrated, never
re-normalised within a crop), and anything below the provisional threshold — or a photo that
does not look like the selected crop — becomes "unsure". Output is a *possible* condition,
never a diagnosis.
"""

import io
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Protocol

import numpy as np
from PIL import Image, ImageOps

from backend.app.config import REPO_ROOT

log = logging.getLogger("irminsul.ai")

MODEL_NAME = "plantvillage-mobilenetv2"
MODELS_ROOT = REPO_ROOT / "ai" / "models" / MODEL_NAME

Status = Literal["ok", "unsure"]
UnsureReason = Literal["low_confidence", "not_this_crop"]


class Session(Protocol):
    def run(self, output_names: Any, input_feed: Any, run_options: Any = None) -> Sequence[Any]: ...


class ModelUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Bundle:
    session: Session
    preprocess: dict[str, Any]
    classes: list[dict[str, Any]]
    thresholds: dict[str, Any]
    manifest: dict[str, Any]

    @property
    def version(self) -> str:
        return f"{self.manifest['name']}@{str(self.manifest['revision'])[:7]}"


@dataclass(frozen=True)
class Candidate:
    disease: str
    label: str
    probability: float
    healthy: bool


@dataclass(frozen=True)
class Screening:
    status: Status
    reason: UnsureReason | None
    crop: str
    top: list[Candidate]
    crop_probability_mass: float
    threshold: float
    threshold_status: str
    model_version: str


# --- preprocessing -------------------------------------------------------------


def preprocess(image: Image.Image, cfg: dict[str, Any]) -> np.ndarray:
    """Resize shortest edge, centre-crop, rescale, normalise → NCHW float32 (model config)."""
    img = ImageOps.exif_transpose(image).convert("RGB")
    target = int(cfg["resize_shortest_edge"])
    w, h = img.size
    scale = target / min(w, h)
    img = img.resize(
        (max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.BILINEAR
    )
    ch, cw = (int(v) for v in cfg["center_crop"])
    w, h = img.size
    left, top = (w - cw) // 2, (h - ch) // 2
    img = img.crop((left, top, left + cw, top + ch))
    arr = np.asarray(img, dtype=np.float32) * float(cfg["rescale_factor"])
    arr = (arr - np.asarray(cfg["mean"], dtype=np.float32)) / np.asarray(
        cfg["std"], dtype=np.float32
    )
    return arr.transpose(2, 0, 1)[np.newaxis, ...].astype(np.float32)


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    z = logits.astype(np.float64) / temperature
    z -= z.max()
    e = np.exp(z)
    return e / e.sum()


# --- output mapping ------------------------------------------------------------------


def interpret(probs: np.ndarray, bundle: Bundle, crop: str, top_k: int = 3) -> Screening:
    th = bundle.thresholds
    idx = [c["index"] for c in bundle.classes if c["crop"] == crop]
    if not idx:
        raise ValueError(f"Model has no classes for crop {crop!r}")
    mass = float(probs[idx].sum())
    ranked = sorted(idx, key=lambda i: float(probs[i]), reverse=True)[:top_k]
    by_index = {c["index"]: c for c in bundle.classes}
    top = [
        Candidate(
            disease=by_index[i]["disease"],
            label=by_index[i]["label"],
            probability=round(float(probs[i]), 4),
            healthy=bool(by_index[i]["healthy"]),
        )
        for i in ranked
    ]
    threshold = float(th["confidence_threshold"])
    if mass < float(th["crop_mass_min"]):
        status, reason = "unsure", "not_this_crop"
    elif top[0].probability < threshold:
        status, reason = "unsure", "low_confidence"
    else:
        status, reason = "ok", None
    return Screening(
        status=status,
        reason=reason,
        crop=crop,
        top=top,
        crop_probability_mass=round(mass, 4),
        threshold=threshold,
        threshold_status=str(th.get("confidence_threshold_status", "provisional")),
        model_version=bundle.version,
    )


def run(bundle: Bundle, image: Image.Image, crop: str) -> Screening:
    x = preprocess(image, bundle.preprocess)
    logits = np.asarray(bundle.session.run(["logits"], {"pixel_values": x})[0])[0]
    probs = softmax(logits, float(bundle.thresholds.get("temperature", 1.0)))
    return interpret(probs, bundle, crop)


def supported_crops(bundle: Bundle) -> list[str]:
    return list(bundle.thresholds.get("supported_crops", []))


# --- loading ---------------------------------------------------------------------


def _model_dir() -> Path:
    if not MODELS_ROOT.is_dir():
        raise ModelUnavailable("Model files not found; run scripts/export_model.py")
    dirs = sorted(
        (d for d in MODELS_ROOT.iterdir() if (d / "manifest.json").is_file()), reverse=True
    )
    if not dirs:
        raise ModelUnavailable("No exported model revision found")
    return dirs[0]


@lru_cache(maxsize=1)
def load_bundle() -> Bundle:
    """Lazy, cached load (Render free tier RAM: keep one session, CPU provider only)."""
    import hashlib

    import onnxruntime as ort

    d = _model_dir()
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    model_path = d / "model.onnx"
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if digest != manifest["model_sha256"]:
        raise ModelUnavailable("Model file checksum does not match its manifest")
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(model_path), sess_options=opts, providers=["CPUExecutionProvider"]
    )
    log.info("Loaded screening model %s", manifest["revision"])
    return Bundle(
        session=session,
        preprocess=json.loads((d / "preprocess.json").read_text(encoding="utf-8")),
        classes=json.loads((d / "class_map.json").read_text(encoding="utf-8")),
        thresholds=json.loads((d / "thresholds.json").read_text(encoding="utf-8")),
        manifest=manifest,
    )


def open_image(data: bytes) -> Image.Image:
    """Decode an already-validated upload."""
    return Image.open(io.BytesIO(data))
