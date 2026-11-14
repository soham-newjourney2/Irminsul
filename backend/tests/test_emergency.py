"""M6 exit criteria: a simulated event finds affected records and proposes capacity-checked
relocation options; confirmations are audited (planning §12)."""

from typing import Any

import httpx
import pytest

from backend.app.db.client import mongo
from backend.app.integrations import osrm, routes
from backend.app.modules.aquasentinel import service as aqua
from backend.app.modules.weather import service as weather
from backend.tests.conftest import UserFactory

pytestmark = pytest.mark.usefixtures("test_db")
INSIDE = {"lat": 22.88, "lng": 88.40}  # inside the simulated Hooghly polygon
FAR_OUT = {"lat": 23.24, "lng": 87.86}  # Bardhaman, outside
NEAR_OUT = {"lat": 22.70, "lng": 88.35}  # just south of the polygon


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(lat1: float, lng1: float, lat2: float, lng2: float, **_: Any) -> osrm.Distance:
        return osrm.estimate(lat1, lng1, lat2, lng2)

    monkeypatch.setattr(osrm, "road_distance", fake)
    monkeypatch.setattr(routes.osrm, "road_distance", fake)


async def _facility(
    op: httpx.AsyncClient, name: str, loc: dict[str, float], cap_t: str, crops: list[str]
) -> dict[str, Any]:
    r = await op.post(
        "/api/v1/storage/facilities",
        json={
            "name": name,
            "district": "Hooghly",
            "location": loc,
            "commodities": crops,
            "capacity": cap_t,
            "contact_email": "s@example.org",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _setup(make_user: UserFactory) -> dict[str, Any]:
    admin, _ = await make_user("admin")
    op, _ = await make_user("storage_operator")
    other_op, _ = await make_user("storage_operator")
    farmer, farmer_doc = await make_user("farmer")
    inside = await _facility(op, "Chinsurah Cold", INSIDE, "5", ["potato", "tomato"])
    near = await _facility(other_op, "South Cold", NEAR_OUT, "2", ["potato"])
    far = await _facility(other_op, "Bardhaman Cold", FAR_OUT, "10", ["potato"])
    tiny = await _facility(other_op, "Tiny Cold", {"lat": 22.65, "lng": 88.30}, "0.2", ["potato"])
    tomato_only = await _facility(
        other_op, "Tomato Cold", {"lat": 22.68, "lng": 88.33}, "10", ["tomato"]
    )
    farm = (
        await farmer.post(
            "/api/v1/farms",
            json={
                "name": "River plot",
                "district": "Hooghly",
                "location": {"lat": 23.0, "lng": 88.3},
            },
        )
    ).json()["data"]
    batch = (
        await farmer.post(
            "/api/v1/batches",
            json={
                "farm_id": farm["id"],
                "commodity": "potato",
                "harvest_date": "2026-11-01",
                "qty": "1",
                "unit": "tonne",
            },
        )
    ).json()["data"]
    b = (
        await farmer.post(
            "/api/v1/storage/bookings",
            json={
                "facility_id": inside["id"],
                "batch_id": batch["id"],
                "commodity": "potato",
                "qty": "1",
                "unit": "tonne",
                "start_date": "2027-01-10",
                "end_date": "2027-03-10",
            },
        )
    ).json()["data"]
    await op.post(f"/api/v1/storage/bookings/{b['id']}/accept", json={})
    await op.post(f"/api/v1/storage/bookings/{b['id']}/check-in", json={})
    return locals()


async def test_trigger_finds_exposure_and_proposes_options(make_user: UserFactory) -> None:
    s = await _setup(make_user)
    admin, op, farmer = s["admin"], s["op"], s["farmer"]
    assert (
        await op.post("/api/v1/admin/demo/flood/trigger", json={"scenario_id": "hooghly_riverside"})
    ).status_code == 403
    r = await admin.post(
        "/api/v1/admin/demo/flood/trigger", json={"scenario_id": "hooghly_riverside"}
    )
    assert r.status_code == 200, r.text
    ev = r.json()["data"]
    assert ev["simulated"] is True and "SIMULATED" in ev["note"]
    assert ev["exposure_counts"]["farms"] == 1 and ev["exposure_counts"]["facilities"] == 1
    assert ev["exposure_counts"]["stored_lots"] == 1
    again = await admin.post(
        "/api/v1/admin/demo/flood/trigger", json={"scenario_id": "hooghly_riverside"}
    )
    assert again.status_code == 409

    exp = (await admin.get(f"/api/v1/emergencies/{ev['id']}/exposure")).json()["data"]
    assert [f["name"] for f in exp["facilities"]] == ["Chinsurah Cold"]
    f_exp = (await farmer.get(f"/api/v1/emergencies/{ev['id']}/exposure")).json()["data"]
    assert len(f_exp["farms"]) == 1 and f_exp["facilities"] == []
    o_exp = (await s["other_op"].get(f"/api/v1/emergencies/{ev['id']}/exposure")).json()["data"]
    assert o_exp["stored_lots"] == [] and o_exp["facilities"] == []

    plans = (
        await op.get(
            f"/api/v1/emergencies/{ev['id']}/relocations", params={"rate_per_km_per_quintal": "3"}
        )
    ).json()["data"]
    assert len(plans) == 1
    names = [o["name"] for o in plans[0]["options"]]
    # outside polygon + stores potato + 1 t free: tiny (0.2 t) and tomato-only are excluded
    assert names == ["South Cold", "Bardhaman Cold"]
    assert all(o["distance_source"] == "haversine_estimate" for o in plans[0]["options"])
    o1 = plans[0]["options"][0]
    assert o1["cost_paise"] == round(o1["distance_km"] * 300 * 1000 / 100)
    assert o1["fit_pct"] == 50.0  # 1 t into 2 t free

    assert mongo.db is not None
    kinds = {
        n["kind"] async for n in mongo.db.notifications.find({"user_id": s["farmer_doc"]["_id"]})
    }
    assert {"emergency.farm_exposed", "emergency.stock_exposed"} <= kinds


async def test_confirm_creates_booking_request_event_and_audit(make_user: UserFactory) -> None:
    s = await _setup(make_user)
    admin, op, farmer = s["admin"], s["op"], s["farmer"]
    ev = (
        await admin.post(
            "/api/v1/admin/demo/flood/trigger", json={"scenario_id": "hooghly_riverside"}
        )
    ).json()["data"]
    plan = (await op.get(f"/api/v1/emergencies/{ev['id']}/relocations")).json()["data"][0]
    target = plan["options"][0]["facility_id"]
    assert (
        await farmer.post(
            f"/api/v1/emergencies/relocations/{plan['id']}/confirm", json={"facility_id": target}
        )
    ).status_code == 403
    assert (
        await s["other_op"].post(
            f"/api/v1/emergencies/relocations/{plan['id']}/confirm", json={"facility_id": target}
        )
    ).status_code == 404
    bad = await op.post(
        f"/api/v1/emergencies/relocations/{plan['id']}/confirm",
        json={"facility_id": s["tiny"]["id"]},
    )
    assert bad.status_code == 422

    r = await op.post(
        f"/api/v1/emergencies/relocations/{plan['id']}/confirm", json={"facility_id": target}
    )
    assert r.status_code == 200, r.text
    done = r.json()["data"]
    assert done["status"] == "confirmed" and done["new_booking_id"]
    assert (
        await op.post(
            f"/api/v1/emergencies/relocations/{plan['id']}/confirm", json={"facility_id": target}
        )
    ).status_code == 409

    # A normal booking REQUEST at the target — its operator still decides; nothing moved yet.
    bookings = (await s["other_op"].get("/api/v1/storage/bookings")).json()["data"]
    req = next(b for b in bookings if b["id"] == done["new_booking_id"])
    assert req["status"] == "requested" and req["batch_id"] == s["batch"]["id"]
    assert mongo.db is not None
    audits = [
        a["action"]
        async for a in mongo.db.audit_logs.find(
            {"action": {"$in": ["relocation.confirm", "demo.flood_trigger"]}}
        )
    ]
    assert sorted(audits) == ["demo.flood_trigger", "relocation.confirm"]
    events = (await farmer.get(f"/api/v1/batches/{s['batch']['id']}")).json()["data"]["events"]
    assert events[-1]["type"] == "relocated" and events[-1]["payload"]["status"] == "planned"
    assert (await farmer.get(f"/api/v1/batches/{s['batch']['id']}/verify")).json()["data"][
        "valid"
    ] is True


async def test_capacity_rechecked_at_confirm(make_user: UserFactory) -> None:
    s = await _setup(make_user)
    admin, op = s["admin"], s["op"]
    ev = (
        await admin.post(
            "/api/v1/admin/demo/flood/trigger", json={"scenario_id": "hooghly_riverside"}
        )
    ).json()["data"]
    plan = (await op.get(f"/api/v1/emergencies/{ev['id']}/relocations")).json()["data"][0]
    near = s["near"]["id"]
    assert mongo.db is not None
    from bson import ObjectId

    await mongo.db.storage_facilities.update_one(
        {"_id": ObjectId(near)}, {"$set": {"reserved_kg": 1500}}
    )  # filled meanwhile
    r = await op.post(
        f"/api/v1/emergencies/relocations/{plan['id']}/confirm", json={"facility_id": near}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_capacity"


async def test_close_expires_open_plans(make_user: UserFactory) -> None:
    s = await _setup(make_user)
    admin, op = s["admin"], s["op"]
    ev = (
        await admin.post(
            "/api/v1/admin/demo/flood/trigger", json={"scenario_id": "hooghly_riverside"}
        )
    ).json()["data"]
    assert (await op.post(f"/api/v1/emergencies/{ev['id']}/close")).status_code == 403
    closed = await admin.post(f"/api/v1/emergencies/{ev['id']}/close")
    assert closed.json()["data"]["status"] == "closed"
    plan = (await op.get(f"/api/v1/emergencies/{ev['id']}/relocations")).json()["data"][0]
    assert plan["status"] == "expired"


async def test_heavy_rain_alert_persisted_once(
    make_user: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta, timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(ist).date()
    days = [(today + timedelta(days=i)).isoformat() for i in range(3)]
    hours = [
        (datetime.combine(today, datetime.min.time()) + timedelta(hours=i)).strftime(
            "%Y-%m-%dT%H:%M"
        )
        for i in range(72)
    ]
    forecast = {
        "timezone": "Asia/Kolkata",
        "daily": {
            "time": days,
            "precipitation_sum": [0.0, 120.0, 0.0],
            "temperature_2m_max": [30] * 3,
            "temperature_2m_min": [24] * 3,
        },
        "hourly": {
            "time": hours,
            "temperature_2m": [27] * 72,
            "relative_humidity_2m": [70] * 72,
            "precipitation": [0] * 72,
        },
        "fetched_at": datetime.now(UTC).isoformat(),
    }

    async def fake_forecast(db: Any, point: Any) -> tuple[dict[str, Any], bool, bool]:
        return forecast, True, False

    monkeypatch.setattr(weather, "get_forecast", fake_forecast)
    farmer, farmer_doc = await make_user("farmer")
    await farmer.post(
        "/api/v1/farms",
        json={"name": "P", "district": "Hooghly", "location": {"lat": 22.9, "lng": 88.39}},
    )
    assert mongo.db is not None
    assert await aqua.check_heavy_rain(mongo.db) == 1
    assert await aqua.check_heavy_rain(mongo.db) == 0  # deduplicated
    rows = (await farmer.get("/api/v1/weather/alerts")).json()["data"]
    assert len(rows) == 1 and rows[0]["label"] == "very_heavy" and rows[0]["verified"] is False
    assert (
        await mongo.db.notifications.count_documents(
            {"user_id": farmer_doc["_id"], "kind": "weather.heavy_rain"}
        )
        == 1
    )
    layer = (await farmer.get("/api/v1/aquasentinel/observations")).json()
    assert layer["data"][0]["next_3_days_mm"] == 120.0 and layer["data"][0]["kind"] == "forecast"
    assert "not available" in layer["meta"]["water_quality"]
