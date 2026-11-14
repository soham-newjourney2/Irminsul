"""One-off: geocode West Bengal mandi markets from the dated snapshot with OSM Nominatim.

Usage: uv run python -I scripts/geocode_markets.py
Policy (operations.osmfoundation.org/policies/nominatim): ≤ 1 request/s, identifying
User-Agent, results cached — this script is resumable and never re-queries a market.
Only market/district names are sent. Output: data/markets_wb.json (ODbL attribution).
"""

import csv
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "markets_wb.json"
URL = "https://nominatim.openstreetmap.org/search"
UA = "IrminsulHackathon/0.1 (one-off geocoding of public market names)"
# Loose West Bengal bounding box (same as backend/app/core/geo.py).
LAT_MIN, LAT_MAX, LNG_MIN, LNG_MAX = 21.4, 27.4, 85.7, 90.0


def snapshot() -> Path:
    files = sorted((ROOT / "data").glob("mandi_snapshot_*.csv"))
    if not files:
        sys.exit("No snapshot; run scripts/build_mandi_snapshot.py first")
    return files[-1]


def clean_market(name: str) -> str:
    n = re.sub(r"\bAPMC\b|\(.*?\)", " ", name, flags=re.I)
    n = n.replace("/", " ")
    return re.sub(r"\s+", " ", n).strip()


def inside_wb(lat: float, lng: float) -> bool:
    return LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX


def query(client: httpx.Client, q: str) -> dict | None:
    r = client.get(
        URL,
        params={
            "q": q,
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": "in",
            "viewbox": f"{LNG_MIN},{LAT_MAX},{LNG_MAX},{LAT_MIN}",
            "bounded": 1,
        },
    )
    time.sleep(1.1)  # stay under 1 request / second
    if r.status_code != 200:
        print(f"  HTTP {r.status_code} for {q!r}")
        return None
    hits = r.json()
    if not hits:
        return None
    lat, lng = float(hits[0]["lat"]), float(hits[0]["lon"])
    if not inside_wb(lat, lng):
        return None
    return {"lat": round(lat, 5), "lng": round(lng, 5), "display_name": hits[0].get("display_name")}


def main() -> int:
    # Same market appears with and without the "APMC" suffix → group by cleaned name.
    pairs: dict[tuple[str, str], dict[str, set[str]]] = {}
    with snapshot().open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            g = pairs.setdefault(
                (row["District"], clean_market(row["Market"])), {"crops": set(), "aliases": set()}
            )
            g["crops"].add(row["crop"])
            g["aliases"].add(row["Market"])
    done: dict[str, dict] = {}
    if OUT.is_file():
        done = {m["key"]: m for m in json.loads(OUT.read_text(encoding="utf-8"))["markets"]}
    district_cache: dict[str, dict | None] = {}
    with httpx.Client(timeout=30, headers={"User-Agent": UA}) as client:
        for i, ((district, name), group) in enumerate(sorted(pairs.items()), 1):
            key = f"{district}|{name}"
            if key in done:
                continue
            hit = query(client, f"{name}, {district}, West Bengal, India")
            precision = "market"
            if hit is None:
                hit = query(client, f"{name}, West Bengal, India")
            if hit is None:
                if district not in district_cache:
                    district_cache[district] = query(
                        client, f"{district} district, West Bengal, India"
                    )
                hit, precision = district_cache[district], "district"
            done[key] = {
                "key": key,
                "district": district,
                "market": name,
                "aliases": sorted(group["aliases"]),
                "crops": sorted(group["crops"]),
                "location": {"lat": hit["lat"], "lng": hit["lng"]} if hit else None,
                "precision": precision if hit else "unknown",
                "matched": hit.get("display_name") if hit else None,
            }
            print(f"[{i}/{len(pairs)}] {key} -> {done[key]['precision']}")
            if i % 10 == 0:
                _save(done)
    _save(done)
    counts: dict[str, int] = {}
    for m in done.values():
        counts[m["precision"]] = counts.get(m["precision"], 0) + 1
    print("precision counts:", counts)
    return 0


def _save(done: dict[str, dict]) -> None:
    OUT.write_text(
        json.dumps(
            {
                "source": "OpenStreetMap Nominatim geocoding of AGMARKNET market names",
                "attribution": "Data © OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)",
                "note": "Approximate. 'district' precision means the district's position was used.",
                "geocoded_at": time.strftime("%Y-%m-%d"),
                "markets": sorted(done.values(), key=lambda m: m["key"]),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
