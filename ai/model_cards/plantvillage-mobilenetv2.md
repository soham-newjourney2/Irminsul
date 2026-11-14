# Model card — crop screening (potato, tomato)

**Shown to users as "possible condition", never a diagnosis.**

| | |
|---|---|
| Source | [`LourivalGontijo/plantvillage-mobilenetv2`](https://huggingface.co/LourivalGontijo/plantvillage-mobilenetv2) |
| Pinned revision | `9e3c97cf1e63e2a665a27c7bccd0ac067a2dbe5d` (repo last modified 2026-10-17) |
| License | Apache-2.0 (training data: PlantVillage; Cropped-PlantDoc, CC BY 4.0, for 27 classes) |
| Architecture | MobileNetV2 1.0/224 (fine-tuned from `google/mobilenet_v2_1.0_224`), 38 classes |
| Our artefact | ONNX opset 17, 9.2 MB, exported by `scripts/export_model.py`; SHA-256 in `manifest.json`, checked at load |
| Export parity | max \|logit diff\| torch vs onnxruntime = 1.9e-6 |
| Runtime | onnxruntime CPU, one session, lazy-loaded |
| Approved by | Owner, 2026-11-14 |

## What Irminsul uses
- Classes: potato (early blight, late blight, healthy) and tomato (bacterial spot, early blight, late blight, leaf mold, Septoria leaf spot, spider mites, target spot, yellow leaf curl virus, mosaic virus, healthy). The other 25 PlantVillage classes still exist in the model; they are used only to notice when a photo does not look like the chosen crop.
- **Rice and jute are not supported** (rice deferred by owner decision; jute out of scope).
- Preprocessing (from the model's `preprocessor_config.json`): resize shortest edge to 256 (bilinear), centre crop 224, ×1/255, normalise mean 0.5 / std 0.5, RGB, NCHW.
- Calibration: logits divided by the published temperature **0.8845** (`calibration.json`, fitted on PlantDoc validation).

## Decision rules
| Rule | Value | Status |
|---|---|---|
| "Not sure" if top probability within the chosen crop is below | **0.6** | **Provisional.** Planning default; the source card recommends 0.5 on lab images, its own field check used 0.85 |
| "Doesn't look like a {crop} leaf" if the probability mass on that crop's classes is below | 0.5 | Our rule, provisional |
| Probabilities are reported as the model gives them | — | never re-normalised within a crop |

Unsure answers tell the farmer to retake the photo (one leaf, daylight, centred) or consult their local KVK / agriculture extension officer.

## Reported performance (from the source model card — not our measurement)
| Test | Result |
|---|---|
| PlantVillage held-out test split (5,430 lab images) | accuracy 99.17 %, macro-F1 98.51 % |
| Real-world: 25 Cropped-PlantDoc field/web photos, threshold 0.85 | **end-to-end pass rate 16.0 %** (95 % CI 6.4–34.7 %); 16 of 25 answered "not sure" |

The source card itself says the lab figure is an **upper bound** (plain backgrounds; the same leaf can appear in train and test), and that the real-world figures are the more honest ones.

## Limitations (from the source card, plus ours)
- Lab-style training photos; accuracy on farmers' phone photos is much lower.
- Only 38 known classes: other diseases, nutrient deficiencies and pest damage are forced into the nearest class — the threshold and "not sure" path are the safeguard.
- One leaf per photo; mixed infections and whole-plant shots are out of scope.
- Softmax confidence remains somewhat over-confident after temperature scaling.
- No evaluation on West Bengal varieties or local field conditions.
- Guidance shown with a result is general, sourced, and **not expert-reviewed**; treatment decisions must be confirmed with local agricultural experts.

## Our sanity check (2026-11-14)
Exported ONNX model + Irminsul's decision rules, on openly licensed Wikimedia Commons photos found by keyword search. Labels come from the file title, **not expert-verified**. 14 images were downloaded; 5 were off-topic search hits (an archive photo, a diagram, a pepper plant) and are excluded from the numbers.

| Result (9 relevant photos) | Count |
|---|---|
| Top-1 class correct | 4 / 9 |
| Confident **and** correct (end-to-end) | **1 / 9** |
| Answered "not sure" | 8 / 9 |
| Confident but wrong | **0 / 9** |

**Reading:** on real field photos the model is mostly unable to answer, but the thresholds keep it from answering wrongly — it said "not sure" instead of guessing. All three potato late-blight photos were classed as "doesn't look like a potato leaf". This matches the source card's 16 % field result. **The tiny sample (9) only shows direction, not accuracy.** Do not present screening as reliable; present it as "possible condition — confirm with your KVK".

| Photo (Wikimedia Commons) | License | Expected | Irminsul answer |
|---|---|---|---|
| [Late blight on potato leaf 2](https://commons.wikimedia.org/wiki/File:Late_blight_on_potato_leaf_2.jpg) | CC BY 3.0 US | potato late blight | not sure — not this crop |
| [Phytophthora infestans on potato leaf](https://commons.wikimedia.org/wiki/File:Phytophthora_infestans_on_potato_leaf.jpg) | CC BY 3.0 US | potato late blight | not sure — not this crop |
| [Phytophthora infestans on potato leaf 2](https://commons.wikimedia.org/wiki/File:Phytophthora_infestans_on_potato_leaf_2.jpg) | CC BY 3.0 US | potato late blight | not sure — not this crop |
| [Tomato late blight leaf curl 2](https://commons.wikimedia.org/wiki/File:Tomato_late_blight_leaf_curl_2_(5816171413).jpg) | CC BY-SA 2.0 | tomato late blight | **possible late blight (0.80)** ✓ |
| [Tomato late blight leaf sporulating lesions 1](https://commons.wikimedia.org/wiki/File:Tomato_late_blight_leaf_sporulating_lesions_1_(5816170621).jpg) | CC0 | tomato late blight | not sure — not this crop (top: late blight 0.46) |
| [Late blight on tomato leaf](https://commons.wikimedia.org/wiki/File:Late_blight_on_tomato_leaf_(7871756748).jpg) | CC BY 2.0 | tomato late blight | not sure — low confidence (top: early blight 0.54) |
| [Yellow curl leaf disease Pj IMG 3162](https://commons.wikimedia.org/wiki/File:Yellow_curl_leaf_disease_Pj_IMG_3162.jpg) | CC0 | tomato yellow leaf curl | not sure — not this crop (top: correct, 0.15) |
| [Tomato Plant Leaves 02](https://commons.wikimedia.org/wiki/File:Tomato_Plant_Leaves_02.jpg) | CC BY-SA 4.0 | tomato healthy | not sure — not this crop |
| [Tomato Plant Leaves 01](https://commons.wikimedia.org/wiki/File:Tomato_Plant_Leaves_01.jpg) | CC BY-SA 4.0 | tomato healthy | not sure — not this crop |

Script: kept outside the repo (one-off); the photos are not redistributed.

**Demo impact (planning §5 step 1):** a real potato field photo will most likely get "not sure". For the demo, use a clear single-leaf photo on a plain background, and keep the "not sure" path visible as a feature, not a failure.
