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

## 4. Storage-rule sources (verified 2026-11-14 → `data/storage_rules.json`)

PDFs downloaded to `data/raw/sources/` (git-ignored) and read locally with `pypdf` (optional `data` group, owner-approved).

| Profile | Band | Source (verbatim) | Status |
|---|---|---|---|
| Table potato | 3–5 °C, 90–95 % RH | NHB cold-storage standard Type 01 (cs1.pdf) p.9: "Table Potato 4°C … 90 – 95%"; p.10: "temperature variation range of ± 1°C" | verified |
| Seed potato | 2–4 °C, 90–95 % RH | cs1.pdf p.9: "critical storage temperature for seed potato is taken as 3 o C ±1 o C" (CPRI advice) | verified |
| Processing potato | 7.2–10 °C, 90–95 % RH | cs1.pdf p.9: "For French Fries 7.2 – 10°C … For Chipping 7.2–10°C" | verified |
| Ripe tomato | 13–15 °C, 85–90 % RH | NHB Type 02 (cs2.pdf) p.11, Group 6 | verified |
| Mature-green tomato | 18–21 °C, 85–90 % RH | cs2.pdf p.11, Group 7 | verified |
| Jute bales | RH ≤ 65 % only | TIS (German Insurance Association) jute page — not an Indian standard | **unverified** |
| Rice / paddy | none | No cited air temperature/RH band found (official figures are grain moisture ≤ 14 %) | no band — sensor checks only |

Alert durations (warning 30 min, critical 120 min, stale 30 min) and plausibility limits are Irminsul assumptions, listed in the rules file and shown in the UI.
