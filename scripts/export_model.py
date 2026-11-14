"""One-time local export: Hugging Face MobileNetV2 (PlantVillage) → ONNX + versioned metadata.

Needs the optional `export` group:  uv sync --group export
Usage:  uv run python -I scripts/export_model.py

Security: pinned revision, safetensors only (no pickle), no remote code, caches under ./tools.
Output: ai/models/plantvillage-mobilenetv2/<rev7>/{model.onnx, preprocess.json,
        class_map.json, thresholds.json, manifest.json}
"""

import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("HF_HOME", str(ROOT / "tools" / "hf-cache"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import numpy as np  # noqa: E402
import onnxruntime as ort  # noqa: E402
import torch  # noqa: E402
from huggingface_hub import hf_hub_download  # noqa: E402
from transformers import MobileNetV2ForImageClassification  # noqa: E402

REPO = "LourivalGontijo/plantvillage-mobilenetv2"
REVISION = "9e3c97cf1e63e2a665a27c7bccd0ac067a2dbe5d"  # pinned 2026-11-14
LICENSE = "apache-2.0"
NAME = "plantvillage-mobilenetv2"
SUPPORTED_CROPS = ("potato", "tomato")
# Planning §4.5: default 0.6, provisional. The model card recommends 0.5 on lab images;
# we keep the stricter value because the card's own field-photo check is weak.
CONFIDENCE_THRESHOLD = 0.6
# Below this share of probability on the selected crop's classes → "doesn't look like <crop>".
CROP_MASS_MIN = 0.5

CROP_ALIASES = {
    "pepper,_bell": "bell_pepper",
    "corn_(maize)": "corn",
    "cherry_(including_sour)": "cherry",
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def class_entry(index: int, label: str) -> dict[str, object]:
    crop_raw, _, disease_raw = label.partition("___")
    crop = CROP_ALIASES.get(crop_raw.lower(), _slug(crop_raw))
    disease = _slug(disease_raw)
    if disease.startswith(crop + "_"):  # "Tomato___Tomato_mosaic_virus" → "mosaic_virus"
        disease = disease[len(crop) + 1 :]
    if disease.startswith("spider_mites"):
        disease = "spider_mites"
    return {
        "index": index,
        "label": label,
        "crop": crop,
        "disease": disease,
        "healthy": disease == "healthy",
    }


def _json(path: str) -> dict:
    return json.loads(
        Path(hf_hub_download(REPO, path, revision=REVISION)).read_text(encoding="utf-8")
    )


class LogitsOnly(torch.nn.Module):
    def __init__(self, model: torch.nn.Module) -> None:
        super().__init__()
        self.model = model

    def forward(self, pixel_values: torch.Tensor) -> torch.Tensor:
        return self.model(pixel_values=pixel_values).logits


def main() -> int:
    out = ROOT / "ai" / "models" / NAME / REVISION[:7]
    out.mkdir(parents=True, exist_ok=True)

    model = MobileNetV2ForImageClassification.from_pretrained(
        REPO, revision=REVISION, use_safetensors=True, trust_remote_code=False
    ).eval()
    pre = _json("preprocessor_config.json")
    calibration = _json("calibration.json")
    card_threshold = _json("threshold.json")

    raw_labels = model.config.id2label or {}
    id2label = {int(k): v for k, v in raw_labels.items()}
    classes = [class_entry(i, id2label[i]) for i in sorted(id2label)]

    onnx_path = out / "model.onnx"
    dummy = torch.zeros(1, 3, pre["crop_size"]["height"], pre["crop_size"]["width"])
    wrapped = LogitsOnly(model).eval()
    torch.onnx.export(
        wrapped,
        (dummy,),
        str(onnx_path),
        input_names=["pixel_values"],
        output_names=["logits"],
        dynamic_axes={"pixel_values": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )

    # Parity check: torch vs onnxruntime on random inputs.
    rng = np.random.default_rng(0)
    sample = rng.uniform(-1, 1, size=(2, *dummy.shape[1:])).astype(np.float32)
    with torch.no_grad():
        ref = wrapped(torch.from_numpy(sample)).numpy()
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    got = sess.run(["logits"], {"pixel_values": sample})[0]
    max_diff = float(np.max(np.abs(ref - got)))
    if max_diff > 1e-3:
        print(f"Parity check FAILED: max |diff| = {max_diff}", file=sys.stderr)
        return 1

    (out / "preprocess.json").write_text(
        json.dumps(
            {
                "resize_shortest_edge": pre["size"]["shortest_edge"],
                "resample": "bilinear" if pre.get("resample") == 2 else pre.get("resample"),
                "center_crop": [pre["crop_size"]["height"], pre["crop_size"]["width"]],
                "rescale_factor": pre["rescale_factor"],
                "mean": pre["image_mean"],
                "std": pre["image_std"],
                "layout": "NCHW",
                "color": "RGB",
                "source": f"{REPO}@{REVISION}/preprocessor_config.json",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (out / "class_map.json").write_text(json.dumps(classes, indent=2), encoding="utf-8")
    (out / "thresholds.json").write_text(
        json.dumps(
            {
                "confidence_threshold": CONFIDENCE_THRESHOLD,
                "confidence_threshold_status": "provisional",
                "model_card_recommended_threshold": card_threshold.get("threshold"),
                "crop_mass_min": CROP_MASS_MIN,
                "temperature": calibration["temperature"],
                "temperature_source": (
                    f"{REPO}@{REVISION}/calibration.json ({calibration.get('split')})"
                ),
                "supported_crops": list(SUPPORTED_CROPS),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    digest = hashlib.sha256(onnx_path.read_bytes()).hexdigest()
    manifest = {
        "name": NAME,
        "repo": REPO,
        "revision": REVISION,
        "license": LICENSE,
        "model_sha256": digest,
        "model_bytes": onnx_path.stat().st_size,
        "num_classes": len(classes),
        "parity_max_abs_diff": max_diff,
        "exported_at": datetime.now(UTC).isoformat(),
        "exporter": {"torch": torch.__version__, "onnxruntime": ort.__version__, "opset": 17},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
