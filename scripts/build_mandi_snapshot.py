# pyright: reportAttributeAccessIssue=false
# (pyarrow.compute functions are generated at import time; pyright cannot see them.)
"""Build the dated West Bengal mandi snapshot (planning §4.5 CSV fallback) from AGMARKNET data.

Source: AGMARKNET (Ministry of Agriculture & Farmers Welfare, GoI) via data.gov.in
"Variety-wise Daily Market Prices Data of Commodity", compiled by Manas Khandelwal (Kaggle,
DOI 10.34740/kaggle/dsv/15888319), mirrored on Hugging Face. Licence: GODL-India.

Needs the optional group:  uv sync --group data
Usage:
  uv run --group data python -I scripts/build_mandi_snapshot.py --inspect
  uv run --group data python -I scripts/build_mandi_snapshot.py
Input:  data/raw/hf-mandi/mandi_daily_<year>.parquet (pinned revision below)
Output: data/mandi_snapshot_<last-date>.csv + .json (provenance)
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "hf-mandi"
DATASET = "DHIVAKARNAIDUSUNKARI/mandi-india-daily-prices-2001-2026"
REVISION = "62ad5b49bc00c60b6303ddf3d74ea0718addb59b"
YEARS = (2025, 2026)
STATE = "West Bengal"
COLUMNS = [
    "State",
    "District",
    "Market",
    "Commodity",
    "Variety",
    "Grade",
    "Arrival_Date",
    "Min_Price",
    "Max_Price",
    "Modal_Price",
]
# Our four crops → regex on AGMARKNET commodity names (exact names confirmed with --inspect).
CROP_PATTERNS = {
    "potato": re.compile(r"^potato$", re.I),
    "tomato": re.compile(r"^tomato$", re.I),
    "rice": re.compile(r"^(rice|paddy \(dhan\)\(common\)|paddy \(common\))$", re.I),
    "jute": re.compile(r"^jute$", re.I),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_wb():
    tables = []
    for y in YEARS:
        path = RAW / f"mandi_daily_{y}.parquet"
        if not path.is_file():
            sys.exit(f"Missing {path}; download it first (see docs/data-sources.md)")
        t = pq.read_table(path, columns=COLUMNS)
        tables.append(t.filter(pc.equal(t["State"], STATE)))
    import pyarrow as pa

    return pa.concat_tables(tables)


def inspect() -> None:
    t = load_wb()
    print(f"West Bengal rows {YEARS}: {t.num_rows}")
    dates = t["Arrival_Date"]
    print("date range:", pc.min(dates).as_py(), "to", pc.max(dates).as_py())
    names = pc.value_counts(t["Commodity"]).to_pylist()
    names.sort(key=lambda r: -r["counts"])
    hits = [n for n in names if re.search(r"potato|tomato|rice|paddy|jute", n["values"], re.I)]
    print("crop-like commodity names:", [(n["values"], n["counts"]) for n in hits])
    for crop, pat in CROP_PATTERNS.items():
        mask = pc.match_substring_regex(t["Commodity"], pat.pattern, ignore_case=True)
        sub = t.filter(mask)
        if sub.num_rows == 0:
            print(f"{crop}: no rows")
            continue
        markets = pc.count_distinct(sub["Market"]).as_py()
        last = pc.max(sub["Arrival_Date"]).as_py()
        print(f"{crop}: rows {sub.num_rows}, markets {markets}, last date {last}")
        row = sub.slice(sub.num_rows - 1, 1).to_pylist()[0]
        print("   sample:", {k: str(v) for k, v in row.items()})


def build() -> None:
    t = load_wb()
    rows = []
    for crop, pat in CROP_PATTERNS.items():
        mask = pc.match_substring_regex(t["Commodity"], pat.pattern, ignore_case=True)
        for r in t.filter(mask).to_pylist():
            rows.append({"crop": crop, **{k: r[k] for k in COLUMNS}})
    if not rows:
        sys.exit("No matching rows")
    rows.sort(key=lambda r: (r["Arrival_Date"], r["crop"], r["Market"]))
    last = max(r["Arrival_Date"] for r in rows)
    first = min(r["Arrival_Date"] for r in rows)
    out = ROOT / "data" / f"mandi_snapshot_{last.isoformat()}.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["crop", *COLUMNS])
        w.writeheader()
        for r in rows:
            w.writerow({**r, "Arrival_Date": r["Arrival_Date"].isoformat()})
    meta = {
        "file": out.name,
        "rows": len(rows),
        "state": STATE,
        "crops": sorted({r["crop"] for r in rows}),
        "arrival_date_range": [first.isoformat(), last.isoformat()],
        "price_unit": "INR per quintal (AGMARKNET convention)",
        "built_at": datetime.now(UTC).isoformat(),
        "source": {
            "original": "AGMARKNET, Ministry of Agriculture & Farmers Welfare, Government of India",
            "original_dataset": "https://www.data.gov.in/resource/variety-wise-daily-market-prices-data-commodity",
            "compiled_by": (
                "Manas Khandelwal, Daily Market Prices of Commodity India (2001-2026), Kaggle"
            ),
            "doi": "https://doi.org/10.34740/kaggle/dsv/15888319",
            "mirror": f"https://huggingface.co/datasets/{DATASET}",
            "mirror_revision": REVISION,
            "licence": "Government Open Data License - India (GODL-India), https://www.data.gov.in/Godl",
            "input_sha256": {
                f"mandi_daily_{y}.parquet": sha256(RAW / f"mandi_daily_{y}.parquet") for y in YEARS
            },
        },
        "is_snapshot": True,
        "note": "Dated snapshot, not live prices. Show the arrival date with every price.",
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(
        json.dumps({k: meta[k] for k in ("file", "rows", "crops", "arrival_date_range")}, indent=2)
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true")
    args = ap.parse_args()
    inspect() if args.inspect else build()
