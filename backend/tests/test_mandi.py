"""Mandi: price normalisation (planning §13), snapshot loading, queries, net realization API."""

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.integrations import osrm
from backend.app.modules.mandi import service
from backend.app.modules.mandi.normalize import (
    clean_market,
    market_key,
    normalise_row,
    rupees_per_quintal_to_paise,
)
from backend.tests.conftest import UserFactory

ROW = {
    "crop": "potato",
    "State": "West Bengal",
    "District": "Hooghly",
    "Market": "Pandua APMC",
    "Commodity": "Potato",
    "Variety": "Jyoti",
    "Grade": "FAQ",
    "Arrival_Date": "2026-04-20",
    "Min_Price": "660.0",
    "Max_Price": "730.0",
    "Modal_Price": "700.0",
}


def test_price_normalisation_to_paise() -> None:
    assert rupees_per_quintal_to_paise("1250.5") == 125050
    assert rupees_per_quintal_to_paise(700) == 70000
    for bad in (None, "", "0", "-5", "abc"):
        assert rupees_per_quintal_to_paise(bad) is None


def test_market_name_cleaning_merges_aliases() -> None:
    assert clean_market("Bishnupur (Bankura) APMC") == "Bishnupur"
    assert clean_market("Egra/contai APMC") == "Egra contai"
    assert market_key("Alipurduar", "Alipurduar APMC") == market_key("Alipurduar", "Alipurduar")


def test_normalise_row_accepts_and_rejects() -> None:
    ok = normalise_row(ROW)
    assert ok is not None
    assert ok["modal_price_paise_per_quintal"] == 70000
    assert ok["market"] == "Pandua"
    assert ok["crop"] == "potato"
    paddy = normalise_row(ROW | {"Commodity": "Paddy (Dhan)(Common)"})
    assert paddy is not None and paddy["crop"] == "rice"
    assert normalise_row(ROW | {"Min_Price": "800"}) is None  # min > modal
    assert normalise_row(ROW | {"Commodity": "Onion"}) is None
    assert normalise_row(ROW | {"Arrival_Date": "20/04/2026"}) is None


def test_moving_average_labelled_window() -> None:
    assert service.moving_average([1, 2, 3, 4, 5, 6, 7, 8], 7) == [None] * 6 + [4.0, 5.0]


# --- DB-backed -------------------------------------------------------------------


def _write_snapshot(tmp_path: Path) -> Path:
    rows = [
        ROW,
        ROW | {"Arrival_Date": "2026-04-19", "Modal_Price": "690.0"},
        ROW | {"Market": "Pandua", "Arrival_Date": "2026-04-18", "Modal_Price": "680.0"},  # alias
        ROW
        | {
            "District": "Kolkata",
            "Market": "Sealdah Koley Market APMC",
            "Min_Price": "900",
            "Max_Price": "1100",
            "Modal_Price": "1000",
        },
        ROW | {"Min_Price": "900"},  # invalid: min > modal
    ]
    path = tmp_path / "mandi_snapshot_2026-04-20.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(ROW))
        w.writeheader()
        w.writerows(rows)
    path.with_suffix(".json").write_text(
        json.dumps({"arrival_date_range": ["2026-04-18", "2026-04-20"]})
    )
    return path


@pytest.fixture
async def loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, test_db: None) -> dict[str, Any]:
    markets = {
        "attribution": "Data © OpenStreetMap contributors, ODbL 1.0",
        "markets": [
            {
                "key": "Hooghly|Pandua",
                "district": "Hooghly",
                "market": "Pandua",
                "crops": ["potato"],
                "location": {"lat": 23.08, "lng": 88.28},
                "precision": "market",
            },
            {
                "key": "Kolkata|Sealdah Koley Market",
                "district": "Kolkata",
                "market": "Sealdah Koley Market",
                "crops": ["potato"],
                "location": {"lat": 22.567, "lng": 88.37},
                "precision": "market",
            },
        ],
    }
    data_dir = tmp_path
    (data_dir / "markets_wb.json").write_text(json.dumps(markets), encoding="utf-8")
    snap = _write_snapshot(data_dir)
    monkeypatch.setattr(service, "DATA", data_dir)
    from backend.app.db.client import mongo

    assert mongo.db is not None
    result = await service.load_snapshot(mongo.db, snap)
    return result


async def test_snapshot_load_is_idempotent(loaded: dict[str, Any]) -> None:
    assert (loaded["accepted"], loaded["rejected"], loaded["new"]) == (4, 1, 4)
    from backend.app.db.client import mongo

    assert mongo.db is not None
    again = await service.load_snapshot(mongo.db, service.DATA / "mandi_snapshot_2026-04-20.csv")
    assert again["new"] == 0
    assert await mongo.db.price_observations.count_documents({}) == 4


async def test_latest_and_history_endpoints(make_user: UserFactory, loaded: dict[str, Any]) -> None:
    farmer, _ = await make_user("farmer")
    r = await farmer.get("/api/v1/mandi-prices/latest", params={"crop": "potato"})
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert {x["market"] for x in rows} == {"Pandua", "Sealdah Koley Market"}
    pandua = next(x for x in rows if x["market"] == "Pandua")
    assert pandua["arrival_date"] == "2026-04-20"
    assert pandua["modal_price_paise_per_quintal"] == 70000
    assert pandua["market_location"]["precision"] == "market"
    assert r.json()["meta"]["is_snapshot"] is True

    h = await farmer.get(
        "/api/v1/mandi-prices/history", params={"crop": "potato", "market_key": "Hooghly|Pandua"}
    )
    pts = h.json()["data"]["points"]
    assert [p["date"] for p in pts] == ["2026-04-18", "2026-04-19", "2026-04-20"]  # aliases merged
    assert "trend, not forecast" in h.json()["data"]["trend_label"]


async def test_net_realization_endpoint(
    make_user: UserFactory, loaded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_route(
        lat1: float, lng1: float, lat2: float, lng2: float, **_: Any
    ) -> osrm.Distance:
        return osrm.estimate(lat1, lng1, lat2, lng2)

    monkeypatch.setattr(osrm, "road_distance", fake_route)
    farmer, _ = await make_user("farmer")
    other, _ = await make_user("farmer")
    farm = await farmer.post(
        "/api/v1/farms",
        json={"name": "P", "district": "Hooghly", "location": {"lat": 22.9, "lng": 88.39}},
    )
    body = {
        "farm_id": farm.json()["data"]["id"],
        "crop": "potato",
        "qty": "10",
        "unit": "quintal",
        "transport_rate_per_km_per_quintal": "3",
        "fees_pct": 2,
        "practical_distance_km": 30,
    }
    r = await farmer.post("/api/v1/markets/net-realization", json=body)
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert len(rows) == 2
    assert all(x["distance_source"] == "haversine_estimate" for x in rows)
    for x in rows:
        assert x["net_paise"] == x["gross_paise"] - x["transport_paise"] - x["fees_paise"]
    assert rows[0]["beyond_practical_distance"] is False  # in-range markets listed first
    assert r.json()["meta"]["assumptions"]["transport_rate_paise_per_km_per_quintal"] == 300
    assert (await other.post("/api/v1/markets/net-realization", json=body)).status_code == 404


async def test_admin_refresh_is_audited(make_user: UserFactory, loaded: dict[str, Any]) -> None:
    admin, _ = await make_user("admin")
    farmer, _ = await make_user("farmer")
    assert (await farmer.post("/api/v1/admin/mandi/refresh")).status_code == 403
    r = await admin.post("/api/v1/admin/mandi/refresh")
    assert r.status_code == 200
    assert r.json()["data"]["new"] == 0
    from backend.app.db.client import mongo

    assert mongo.db is not None
    assert await mongo.db.audit_logs.count_documents({"action": "mandi.refresh"}) == 1
