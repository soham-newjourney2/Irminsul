"""Mandi prices (dated AGMARKNET snapshot; live API when data.gov.in recovers), markets,
and net realization. Every price carries its source and arrival date."""

import asyncio
import csv
import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from pymongo import ASCENDING, DESCENDING, UpdateOne
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import BulkWriteError

from backend.app.config import REPO_ROOT, get_settings
from backend.app.core.errors import AppError
from backend.app.core.geo import GeoPoint
from backend.app.db.client import Doc
from backend.app.integrations import osrm
from backend.app.modules.mandi import netcalc
from backend.app.modules.mandi.normalize import normalise_row

log = logging.getLogger("irminsul.mandi")
DATA = REPO_ROOT / "data"
SNAPSHOT_SOURCE = "agmarknet-snapshot"
ROUTE_TTL = timedelta(days=30)
_status: dict[str, bool] = {"loading": False}


def latest_snapshot() -> Path | None:
    files = sorted(DATA.glob("mandi_snapshot_*.csv"))
    return files[-1] if files else None


def _snapshot_meta(path: Path) -> dict[str, Any]:
    meta = path.with_suffix(".json")
    return json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}


# --- loading -------------------------------------------------------------------------


async def load_snapshot(db: AsyncDatabase[Doc], path: Path | None = None) -> dict[str, Any]:
    path = path or latest_snapshot()
    if path is None:
        raise AppError(404, "snapshot_missing", "No mandi snapshot file found")
    meta = _snapshot_meta(path)
    fetched_at = datetime.now(UTC)
    _status["loading"] = True
    try:
        # Markets first, so every price can show its market position as soon as it lands.
        await load_markets(db)
        # CPU-bound parsing runs in a worker thread so the event loop keeps serving requests.
        docs, rejected = await asyncio.to_thread(_parse_snapshot, path, fetched_at)
        written = 0
        for i in range(0, len(docs), 2000):
            written += await _insert_new(db, docs[i : i + 2000])
    finally:
        _status["loading"] = False
    accepted = len(docs)
    result = {
        "file": path.name,
        "accepted": accepted,
        "rejected": rejected,
        "new": written,
        "arrival_date_range": meta.get("arrival_date_range"),
    }
    log.info("Mandi snapshot loaded: %s", result)
    return result


def _parse_snapshot(path: Path, fetched_at: datetime) -> tuple[list[Doc], int]:
    docs: list[Doc] = []
    rejected = 0
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            obs = normalise_row(row)
            if obs is None:
                rejected += 1
                continue
            docs.append(
                {
                    **obs,
                    "schema_version": 1,
                    "source": SNAPSHOT_SOURCE,
                    "snapshot_file": path.name,
                    "observed_at": obs["arrival_date"],
                    "fetched_at": fetched_at,
                    "is_demo": False,
                }
            )
    # Newest first: the latest prices are usable while older history is still loading.
    docs.sort(key=lambda d: d["arrival_date"], reverse=True)
    return docs, rejected


async def _insert_new(db: AsyncDatabase[Doc], batch: list[Doc]) -> int:
    """Unordered insert; rows already present (unique index) are skipped, not overwritten."""
    try:
        return len((await db.price_observations.insert_many(batch, ordered=False)).inserted_ids)
    except BulkWriteError as exc:
        others = [e for e in exc.details.get("writeErrors", []) if e.get("code") != 11000]
        if others:
            raise
        return int(exc.details.get("nInserted", 0))


async def load_markets(db: AsyncDatabase[Doc]) -> int:
    path = DATA / "markets_wb.json"
    if not path.is_file():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    ops = []
    for m in data["markets"]:
        doc: Doc = {
            "schema_version": 1,
            "key": m["key"],
            "district": m["district"],
            "name": m["market"],
            "aliases": m.get("aliases", []),
            "crops": m.get("crops", []),
            "precision": m["precision"],
            "matched": m.get("matched"),
            "source": "osm-nominatim",
            "attribution": data.get("attribution"),
        }
        update: Doc = {"$set": doc}
        if m.get("location"):
            doc["location"] = {
                "type": "Point",
                "coordinates": [m["location"]["lng"], m["location"]["lat"]],
            }
        else:
            update["$unset"] = {"location": ""}
        ops.append(UpdateOne({"key": m["key"]}, update, upsert=True))
    if ops:
        await db.markets.bulk_write(ops, ordered=False)
    return len(ops)


async def ensure_loaded(db: AsyncDatabase[Doc]) -> None:
    """Startup: load the snapshot once if the collection is empty (runs as a background task)."""
    try:
        if await db.price_observations.estimated_document_count() == 0 and latest_snapshot():
            await load_snapshot(db)
    except Exception:
        log.exception("Could not load mandi snapshot at startup")


# --- queries -------------------------------------------------------------------------


async def _markets(db: AsyncDatabase[Doc], keys: list[str]) -> dict[str, Doc]:
    return {m["key"]: m async for m in db.markets.find({"key": {"$in": keys}})}


def _market_view(m: Doc | None) -> dict[str, Any]:
    if not m:
        return {"location": None, "precision": "unknown"}
    loc = m.get("location")
    return {
        "location": {"lat": loc["coordinates"][1], "lng": loc["coordinates"][0]} if loc else None,
        "precision": m["precision"],
    }


async def latest_prices(
    db: AsyncDatabase[Doc], crop: str, district: str | None, limit: int
) -> list[dict[str, Any]]:
    match: Doc = {"crop": crop}
    if district:
        match["district"] = district
    pipeline: list[Doc] = [
        {"$match": match},
        {"$sort": {"arrival_date": -1, "modal_price_paise_per_quintal": -1}},
        {"$group": {"_id": "$market_key", "doc": {"$first": "$$ROOT"}}},
        {"$replaceRoot": {"newRoot": "$doc"}},
        {"$sort": {"arrival_date": -1, "market": 1}},
        {"$limit": limit},
    ]
    rows = await (await db.price_observations.aggregate(pipeline)).to_list()
    markets = await _markets(db, [r["market_key"] for r in rows])
    return [_price_view(r, markets.get(r["market_key"])) for r in rows]


def _price_view(r: Doc, market: Doc | None) -> dict[str, Any]:
    return {
        "market_key": r["market_key"],
        "market": r["market"],
        "district": r["district"],
        "commodity": r["commodity"],
        "variety": r.get("variety"),
        "grade": r.get("grade"),
        "arrival_date": r["arrival_date"],
        "min_price_paise_per_quintal": r["min_price_paise_per_quintal"],
        "max_price_paise_per_quintal": r["max_price_paise_per_quintal"],
        "modal_price_paise_per_quintal": r["modal_price_paise_per_quintal"],
        "source": r["source"],
        "market_location": _market_view(market),
    }


def moving_average(values: list[float], window: int = 7) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < window:
            out.append(None)
        else:
            chunk = values[i + 1 - window : i + 1]
            out.append(round(sum(chunk) / window, 1))
    return out


async def history(db: AsyncDatabase[Doc], crop: str, market_key: str, days: int) -> dict[str, Any]:
    last = await db.price_observations.find_one(
        {"crop": crop, "market_key": market_key}, sort=[("arrival_date", DESCENDING)]
    )
    if last is None:
        raise AppError(404, "not_found", "No prices for this market and crop")
    start = (date.fromisoformat(last["arrival_date"]) - timedelta(days=days)).isoformat()
    pipeline: list[Doc] = [
        {"$match": {"crop": crop, "market_key": market_key, "arrival_date": {"$gte": start}}},
        {
            "$group": {
                "_id": "$arrival_date",
                "modal": {"$avg": "$modal_price_paise_per_quintal"},
                "min": {"$min": "$min_price_paise_per_quintal"},
                "max": {"$max": "$max_price_paise_per_quintal"},
                "varieties": {"$addToSet": "$variety"},
            }
        },
        {"$sort": {"_id": ASCENDING}},
    ]
    rows = await (await db.price_observations.aggregate(pipeline)).to_list()
    modal = [round(r["modal"]) for r in rows]
    ma = moving_average([float(v) for v in modal])
    return {
        "market_key": market_key,
        "market": last["market"],
        "district": last["district"],
        "crop": crop,
        "points": [
            {
                "date": r["_id"],
                "modal_paise_per_quintal": modal[i],
                "min_paise_per_quintal": r["min"],
                "max_paise_per_quintal": r["max"],
                "varieties": sorted(v for v in r["varieties"] if v),
                "trend_7obs_paise": ma[i],
            }
            for i, r in enumerate(rows)
        ],
        "aggregation": "mean of modal prices across varieties per day",
        "trend_label": "7-observation moving average — trend, not forecast",
        "source": last["source"],
    }


async def freshness(db: AsyncDatabase[Doc]) -> dict[str, Any]:
    newest = await db.price_observations.find_one(sort=[("arrival_date", DESCENDING)])
    snap = latest_snapshot()
    return {
        "newest_arrival_date": newest["arrival_date"] if newest else None,
        "source": newest["source"] if newest else None,
        "is_snapshot": bool(newest and newest["source"] == SNAPSHOT_SOURCE),
        "snapshot": _snapshot_meta(snap).get("source") if snap else None,
        "live_api": "unavailable — data.gov.in returns 502 (last checked 2026-11-14)",
        "loading": _status["loading"],
    }


# --- net realization -------------------------------------------------------------------


async def _distance(db: AsyncDatabase[Doc], a: GeoPoint, b: GeoPoint) -> osrm.Distance:
    key = f"{a.lat:.3f},{a.lng:.3f}>{b.lat:.3f},{b.lng:.3f}"
    hit = await db.route_cache.find_one({"key": key})
    if hit and hit["fetched_at"] > datetime.now(UTC) - ROUTE_TTL:
        return osrm.Distance(
            km=hit["km"], source=hit["source"], duration_min=hit.get("duration_min")
        )
    d = await osrm.road_distance(
        a.lat, a.lng, b.lat, b.lng, timeout_s=get_settings().http_timeout_s
    )
    if d.source == "osrm":  # only cache real routes; estimates are recomputed cheaply
        await db.route_cache.update_one(
            {"key": key},
            {
                "$set": {
                    "key": key,
                    "km": d.km,
                    "source": d.source,
                    "duration_min": d.duration_min,
                    "fetched_at": datetime.now(UTC),
                }
            },
            upsert=True,
        )
    return d


async def net_realization(
    db: AsyncDatabase[Doc],
    origin: GeoPoint,
    crop: str,
    qty_kg: int,
    transport_paise_per_km_per_q: int,
    fees_pct: float,
    practical_km: float,
    max_markets: int,
) -> list[dict[str, Any]]:
    prices = await latest_prices(db, crop, None, 300)
    candidates = []
    for p in prices:
        loc = p["market_location"]["location"]
        if loc is None:
            continue
        straight = osrm.haversine_km(origin.lat, origin.lng, loc["lat"], loc["lng"])
        candidates.append((straight, p))
    candidates.sort(key=lambda c: c[0])
    out = []
    for _, p in candidates[:max_markets]:
        loc = p["market_location"]["location"]
        dist = await _distance(db, origin, GeoPoint(lat=loc["lat"], lng=loc["lng"]))
        r = netcalc.compute(
            qty_kg=qty_kg,
            modal_price_paise_per_quintal=p["modal_price_paise_per_quintal"],
            distance_km=dist.km,
            distance_source=dist.source,
            transport_rate_paise_per_km_per_quintal=transport_paise_per_km_per_q,
            fees_pct=fees_pct,
            practical_distance_km=practical_km,
        )
        out.append(
            {
                "market": p,
                "distance_km": dist.km,
                "distance_source": dist.source,
                "duration_min": dist.duration_min,
                "gross_paise": r.gross_paise,
                "transport_paise": r.transport_paise,
                "fees_paise": r.fees_paise,
                "net_paise": r.net_paise,
                "beyond_practical_distance": r.beyond_practical_distance,
            }
        )
    out.sort(key=lambda x: (x["beyond_practical_distance"], -x["net_paise"]))
    return out
