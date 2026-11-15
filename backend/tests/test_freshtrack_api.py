"""FreshTrack API: exit criteria + permissions + notifications + batch events."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from bson import ObjectId

from backend.app.db.client import mongo
from backend.app.modules.freshtrack import service, simulator
from backend.tests.conftest import UserFactory

pytestmark = pytest.mark.usefixtures("test_db")


async def _setup(make_user: UserFactory) -> dict[str, Any]:
    op, op_doc = await make_user("storage_operator")
    farmer, farmer_doc = await make_user("farmer")
    other_op, _ = await make_user("storage_operator")
    admin, _ = await make_user("admin")
    fac = (
        await op.post(
            "/api/v1/storage/facilities",
            json={
                "name": "Chinsurah Cold",
                "district": "Hooghly",
                "location": {"lat": 22.88, "lng": 88.4},
                "commodities": ["potato"],
                "capacity": "5",
                "contact_email": "cold@example.org",
            },
        )
    ).json()["data"]
    zone = (
        await op.post(
            f"/api/v1/storage/facilities/{fac['id']}/zones",
            json={"name": "Chamber A", "commodity": "potato"},
        )
    ).json()["data"]
    farm = (
        await farmer.post(
            "/api/v1/farms",
            json={"name": "P", "district": "Hooghly", "location": {"lat": 22.9, "lng": 88.39}},
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
                "facility_id": fac["id"],
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
    await op.post(f"/api/v1/storage/bookings/{b['id']}/check-in", json={"zone_id": zone["id"]})
    return {
        "op": op,
        "farmer": farmer,
        "other_op": other_op,
        "admin": admin,
        "zone": zone,
        "batch": batch,
        "booking": b,
        "farmer_doc": farmer_doc,
        "op_doc": op_doc,
    }


# One fixed "now" per test run so reading offsets (and excursion durations) are exact.
_BASE = datetime.now(UTC)


async def _reading(
    c: httpx.AsyncClient, zone_id: str, temp: float, minutes_ago: float, rh: float = 92
) -> httpx.Response:
    at = (_BASE - timedelta(minutes=minutes_ago)).isoformat()
    return await c.post(
        "/api/v1/freshtrack/observations",
        json={"zone_id": zone_id, "temp": temp, "rh_pct": rh, "observed_at": at},
    )


async def test_excursion_alert_ack_resolve(make_user: UserFactory) -> None:
    s = await _setup(make_user)
    op, farmer, zid = s["op"], s["farmer"], s["zone"]["id"]
    for m in (60, 50):
        assert (await _reading(op, zid, 4.0, m)).status_code == 201
    # 40 minutes continuously above 5 °C → warning
    last = None
    for m in (40, 30, 20, 10, 0):
        last = await _reading(op, zid, 7.0, m)
    assert last is not None
    alerts = last.json()["data"]["alerts"]
    assert [(a["kind"], a["severity"]) for a in alerts] == [("temp_high", "warning")]
    a = alerts[0]
    assert a["threshold"] == 5.0 and a["peak"] == 7.0 and a["duration_min"] == 40
    assert a["profile"]["source"]["url"].startswith("https://www.nhb.gov.in/")
    assert a["simulated"] is False

    # Farmer whose produce is in the zone sees it and was notified; batch got an exception event.
    f_alerts = (await farmer.get("/api/v1/freshtrack/alerts")).json()["data"]
    assert [x["id"] for x in f_alerts] == [a["id"]]
    assert mongo.db is not None
    kinds = [
        n["kind"] async for n in mongo.db.notifications.find({"user_id": s["farmer_doc"]["_id"]})
    ]
    assert "freshtrack.alert_opened" in kinds
    ev = (await farmer.get(f"/api/v1/batches/{s['batch']['id']}")).json()["data"]["events"]
    assert ev[-1]["type"] == "exception" and ev[-1]["payload"]["kind"] == "temp_high"

    # Farmers cannot act on alerts; other orgs cannot see them.
    assert (
        await farmer.post(f"/api/v1/freshtrack/alerts/{a['id']}/acknowledge", json={})
    ).status_code == 403
    assert (
        await s["other_op"].post(f"/api/v1/freshtrack/alerts/{a['id']}/acknowledge", json={})
    ).status_code == 404

    ack = await op.post(
        f"/api/v1/freshtrack/alerts/{a['id']}/acknowledge", json={"note": "Checking compressor"}
    )
    assert ack.json()["data"]["status"] == "acknowledged"
    body = {
        "findings": "Door seal leaking on chamber A",
        "corrective_action": "Replaced seal, verified pull-down",
    }
    early = await op.post(f"/api/v1/freshtrack/alerts/{a['id']}/resolve", json=body)
    assert early.status_code == 409 and early.json()["error"]["code"] == "condition_active"

    await _reading(op, zid, 4.2, 0)  # back in band → condition cleared, alert stays open
    still = (await op.get("/api/v1/freshtrack/alerts")).json()["data"][0]
    assert still["status"] == "acknowledged" and still["condition_active"] is False
    assert (
        await op.post(
            f"/api/v1/freshtrack/alerts/{a['id']}/resolve",
            json={"findings": "x", "corrective_action": "y"},
        )
    ).status_code == 422
    done = await op.post(f"/api/v1/freshtrack/alerts/{a['id']}/resolve", json=body)
    assert done.status_code == 200
    d = done.json()["data"]
    assert d["status"] == "resolved" and d["inspection"]["corrective_action"].startswith(
        "Replaced seal"
    )
    assert [h["action"] for h in d["history"]] == ["opened", "acknowledged", "resolved"]
    audits = [x["action"] async for x in mongo.db.audit_logs.find({"target_type": "storage_alert"})]
    assert audits == ["alert.acknowledge", "alert.resolve"]
    ev = (await farmer.get(f"/api/v1/batches/{s['batch']['id']}")).json()["data"]["events"]
    assert ev[-1]["type"] == "inspection" and ev[-1]["payload"]["result"] == "resolved"
    assert (await farmer.get(f"/api/v1/batches/{s['batch']['id']}/verify")).json()["data"][
        "valid"
    ] is True


async def test_escalation_to_critical_updates_same_alert(make_user: UserFactory) -> None:
    s = await _setup(make_user)
    op, zid = s["op"], s["zone"]["id"]
    for m in range(150, -1, -10):
        await _reading(op, zid, 6.5, m)
    rows = (await op.get("/api/v1/freshtrack/alerts")).json()["data"]
    assert len(rows) == 1
    assert rows[0]["severity"] == "critical"
    assert "escalated" in [h["action"] for h in rows[0]["history"]]


async def test_stale_sensor_alert_fires(make_user: UserFactory) -> None:
    s = await _setup(make_user)
    op, zid = s["op"], s["zone"]["id"]
    await _reading(op, zid, 4.0, 45)
    assert mongo.db is not None
    assert await service.check_stale(mongo.db) == 1
    rows = (await op.get("/api/v1/freshtrack/alerts")).json()["data"]
    assert rows[0]["kind"] == "stale" and rows[0]["severity"] == "warning"
    await _reading(op, zid, 4.0, 0)  # sensor back → condition cleared
    rows = (await op.get("/api/v1/freshtrack/alerts")).json()["data"]
    assert rows[0]["condition_active"] is False


async def test_observation_validation_and_access(make_user: UserFactory) -> None:
    s = await _setup(make_user)
    op, zid = s["op"], s["zone"]["id"]
    assert (await _reading(op, zid, 4.0, -60)).status_code == 422  # future
    assert (await _reading(op, zid, 4.0, 60 * 24 * 8)).status_code == 422  # > 7 days old
    assert (
        await op.post("/api/v1/freshtrack/observations", json={"zone_id": zid})
    ).status_code == 422
    assert (
        await op.post(
            "/api/v1/freshtrack/observations", json={"zone_id": zid, "temp": 4, "rh_pct": 120}
        )
    ).status_code == 422
    f = await op.post(
        "/api/v1/freshtrack/observations",
        json={"zone_id": zid, "temp": 39.2, "temp_unit": "F", "rh_pct": 92},
    )
    assert f.json()["data"]["temp_c"] == 4.0
    assert (
        await s["other_op"].post(
            "/api/v1/freshtrack/observations", json={"zone_id": zid, "temp": 4}
        )
    ).status_code == 404
    assert (
        await s["farmer"].post("/api/v1/freshtrack/observations", json={"zone_id": zid, "temp": 4})
    ).status_code == 403
    obs = (
        await s["farmer"].get("/api/v1/freshtrack/observations", params={"zone_id": zid})
    ).json()["data"]
    assert obs["profile"]["id"] == "potato_table" and len(obs["readings"]) == 1
    stranger, _ = await make_user("farmer")
    assert (
        await stranger.get("/api/v1/freshtrack/observations", params={"zone_id": zid})
    ).status_code == 404


async def test_implausible_reading_flags_sensor(make_user: UserFactory) -> None:
    s = await _setup(make_user)
    op, zid = s["op"], s["zone"]["id"]
    await _reading(op, zid, 4.0, 5)
    r = await _reading(op, zid, 60.0, 0)
    assert [a["kind"] for a in r.json()["data"]["alerts"]] == ["implausible"]


async def test_admin_inject_and_simulator(make_user: UserFactory) -> None:
    s = await _setup(make_user)
    admin, zid = s["admin"], s["zone"]["id"]
    assert (
        await s["op"].post("/api/v1/admin/demo/freshtrack/inject", json={"zone_id": zid})
    ).status_code == 403
    r = await admin.post(
        "/api/v1/admin/demo/freshtrack/inject",
        json={"zone_id": zid, "kind": "temp_high", "minutes": 45},
    )
    assert r.status_code == 200, r.text
    alerts = r.json()["data"]
    assert alerts[0]["kind"] == "temp_high" and alerts[0]["simulated"] is True
    assert mongo.db is not None
    assert await mongo.db.storage_observations.count_documents({"source": "simulated"}) == 10
    stale = await admin.post(
        "/api/v1/admin/demo/freshtrack/check-stale", params={"minutes_ahead": 60}
    )
    assert (
        stale.json()["data"]["stale_zones"] == 1 and stale.json()["data"]["simulated_time"] is True
    )
    started = await admin.post(
        "/api/v1/admin/demo/freshtrack/simulator/start", json={"zone_id": zid, "interval_s": 5}
    )
    assert started.json()["data"]["started"] is True
    simulator.stop(ObjectId(zid))
    demo_audits = [
        x["action"] async for x in mongo.db.audit_logs.find({"action": {"$regex": "^demo\\."}})
    ]
    assert demo_audits == ["demo.inject", "demo.check_stale", "demo.simulator.start"]


async def test_release_records_observation_summary(make_user: UserFactory) -> None:
    s = await _setup(make_user)
    op, zid = s["op"], s["zone"]["id"]
    for temp in (4.0, 4.5):  # server-timestamped (now), i.e. after the check-in above
        r = await op.post(
            "/api/v1/freshtrack/observations", json={"zone_id": zid, "temp": temp, "rh_pct": 92}
        )
        assert r.status_code == 201
    await op.post(f"/api/v1/storage/bookings/{s['booking']['id']}/release", json={})
    ev = (await s["farmer"].get(f"/api/v1/batches/{s['batch']['id']}")).json()["data"]["events"]
    types = [e["type"] for e in ev]
    assert types[-2:] == ["observation_summary", "released"]
    summary = ev[-2]["payload"]
    assert summary["readings"] == 2 and summary["status"] == "within_band"
