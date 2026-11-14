# Data sources — verification log (M0)

Checked 2026-11-13. "Verified live" means an actual request was made from this machine and the response inspected. Anything not verified is marked **UNVERIFIED** and must not be coded against until it is.

## 1. Mandi prices — data.gov.in (Agmarknet)

| Item | Status |
|---|---|
| Candidate resource | `9ef84268-d588-465a-a308-a864a43d0070` ("Current Daily Price of Various Commodities from Various Markets (Mandi)") |
| Endpoint | `GET https://api.data.gov.in/resource/<id>?api-key=<key>&format=json&limit=N&filters[state.keyword]=West Bengal` |
| Without key | Verified live: `{"error": "Authorization field missing"}` → key required |
| Field names / types, WB commodity spellings (Potato, Tomato, Rice, Jute) | **UNVERIFIED** — needs owner's key. data.gov.in web pages return 403 to automated fetches |
| Price unit (assumed ₹/quintal) | **UNVERIFIED** |

**2026-11-14 re-check:** the key is valid (an invalid key gets 403 in 0.4 s, no key gets 400; ours passes the gateway), but every authenticated query returns **502 after ~60 s** (gateway timeout) — filtered or not, 1 row, JSON or CSV. Their data service is down; live ingestion stays blocked until it recovers.

### Snapshot actually used (verified 2026-11-14)
| Item | Value |
|---|---|
| Original data | AGMARKNET, Ministry of Agriculture & Farmers Welfare, GoI — data.gov.in "Variety-wise Daily Market Prices Data of Commodity" |
| Compiled by | Manas Khandelwal, *Daily Market Prices of Commodity India (2001–2026)*, Kaggle, DOI 10.34740/kaggle/dsv/15888319 |
| Downloaded from | Hugging Face mirror `DHIVAKARNAIDUSUNKARI/mandi-india-daily-prices-2001-2026`, pinned revision `62ad5b49bc00c60b6303ddf3d74ea0718addb59b` (yearly Parquet, 2025 + 2026 files) |
| Licence | Government Open Data License – India (GODL-India) — reuse with attribution |
| Columns (verified) | `State, District, Market, Commodity, Variety, Grade, Arrival_Date, Min_Price, Max_Price, Modal_Price` (+ `Commodity_Code`); no arrivals quantity |
| Price unit | ₹ per quintal (AGMARKNET convention; sample values plausible, e.g. potato modal ₹850/q) |
| WB commodity names | `Potato`, `Tomato`, `Rice`, `Paddy (Dhan)(Common)`, `Paddy (Common)`, `Jute` |
| WB coverage | 2025-01-01 → **2026-04-20**; potato 142 markets, rice 108, tomato 86, jute 40 |
| Output | `data/mandi_snapshot_2026-04-20.csv` (62,951 rows) + `.json` provenance (source, licence, SHA-256 of inputs) — built by `scripts/build_mandi_snapshot.py` |
| Caveat | Snapshot, not live: the newest price is from 2026-04-20. The UI must show the arrival date with every price. Market coordinates are **not** in the data. |

## 2. Weather — Open-Meteo (no key)

| Endpoint | Status |
|---|---|
| `https://api.open-meteo.com/v1/forecast` with `hourly=temperature_2m,relative_humidity_2m,precipitation`, `daily=precipitation_sum,temperature_2m_max,temperature_2m_min`, `timezone=Asia/Kolkata` | Verified live (Kolkata 22.57, 88.36). Units returned: `°C`, `%`, `mm`; times ISO-8601 local, `utc_offset_seconds: 19800` |
| `https://flood-api.open-meteo.com/v1/flood` with `daily=river_discharge` | Verified live; returns `river_discharge` in `m³/s` (GloFAS-based). Optional context layer only; flood *events* stay simulated (decision #7) |

Terms: Open-Meteo free tier is non-commercial; attribution required ("Weather data by Open-Meteo.com", CC BY 4.0).

## 3. Crop screening model — shortlist (owner approves in M4)

All metadata below read live from the Hugging Face API.

| Candidate | Crops / classes | Format, size | License | Notes |
|---|---|---|---|---|
| **A. `onnx-community/mobilenet_v2_1.0_224-plant-disease-identification-ONNX`** | 38 PlantVillage classes incl. Potato (Early/Late blight, Healthy), Tomato (10) | ONNX ready: fp32 9.2 MB, int8 2.7 MB | `other` (base `linkanjarad/...`, license text unclear) | No export needed. License must be confirmed before use |
| **B. `LourivalGontijo/plantvillage-mobilenetv2`** | Same 38 PlantVillage classes | safetensors 9.3 MB → needs ONNX export (optional `torch/transformers/onnx` group) | Apache-2.0 | Publishes `threshold.json`, calibration, PlantVillage test acc 0.992 — **and a real-world field set: 16 % end-to-end pass rate (n=25) at threshold 0.85** |
| **C. `Huyt/rice-leaf-disease-efficientnet-b0`** (rice) | 17 rice classes incl. Healthy | timm, 16 MB → needs export | Apache-2.0 | Reported acc 0.971 on its split; timm transform 224 px, crop_pct 0.875, bicubic |
| D. `prithivMLmods/Rice-Leaf-Disease` (rice) | 5 classes | SigLIP2-base, 372 MB | Apache-2.0 | Too large for Render 512 MB — rejected |

Implication: PlantVillage models are lab-image trained and generalize poorly to field photos (B's own real-world check). Keep the "unsure" path, "possible disease" wording, and a high threshold; model card must state this. Jute → "not supported" (decision #3).

## 4. Storage-rule sources (values extracted in M5, owner verifies)

| Source | Covers | Status |
|---|---|---|
| NHB Technical Standards, Cold Storage Type 01 (NHB-CS-Type 01-2010) — https://www.nhb.gov.in/documents/cs1.pdf | Potato (seed / table / processing), RH bands | PDF reachable (200). Values not yet extracted |
| NHB potato post-harvest guide — https://nhb.gov.in/pdf/vegetable/potato/pot009.pdf | Potato storage conditions | PDF reachable (200). Values not yet extracted |
| USDA ARS Agriculture Handbook 66 — https://purl.fdlp.gov/GPO/gpo66112 | Tomato (mature-green vs ripe), potato, chilling injury | Reachable (redirect). Values not yet extracted |
| FAO post-harvest manual — https://www.fao.org/4/ae075e/ae075e14.htm | Processing-potato temperature | Reachable (200) |
| Rice (grain moisture / storage), jute (fibre storage) | — | **No source chosen yet**; to find an ICAR/FCI/government source in M5 |

No numeric thresholds are recorded here on purpose: secondary snippets were garbled or derived; numbers will be taken from the primary PDFs in M5.
