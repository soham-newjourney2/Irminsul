"""M2 storage: facilities, zones, bookings, capacity invariant."""

import asyncio
from typing import Any

import httpx
import pytest
from bson import ObjectId

from backend.app.db.client import mongo
from backend.tests.conftest import UserFactory

pytestmark = pytest.mark.usefixtures("test_db")

CHINSURAH = {"lat": 22.88, "lng": 88.40}


async def _facility(c: httpx.AsyncClient, **kw: Any) -> dict[str, Any]:
    body = {
        "name": "Chinsurah Cold Store",
        "district": "Hooghly",
        "location": CHINSURAH,
        "commodities": ["potato", "tomato"],
        "capacity": "1",
        "capacity_unit": "tonne",
        "contact_email": "Store@Example.org",
    } | kw
    r = await c.post("/api/v1/storage/facilities", json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _booking(c: httpx.AsyncClient, facility_id: str, **kw: Any) -> dict[str, Any]:
    body = {
        "facility_id": facility_id,
        "commodity": "potato",
        "qty": "300",
        "unit": "kg",
        "start_date": "2027-01-10",
        "end_date": "2027-03-10",
    } | kw
    r = await c.post("/api/v1/storage/bookings", json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _fac_doc(facility_id: str) -> dict[str, Any]:
    assert mongo.db is not None
    doc = await mongo.db.storage_facilities.find_one({"_id": ObjectId(facility_id)})
    assert doc is not None
    return doc


async def test_facility_create_search_and_privacy(make_user: UserFactory) -> None:
    op, _ = await make_user("storage_operator")
    farmer, _ = await make_user("farmer")
    fac = await _facility(op)
    assert fac["capacity_kg"] == 1000
    assert fac["free_kg"] == 1000
    assert fac["contact_email"] == "store@example.org"
    assert fac["is_mine"] is True

    found = (await farmer.get("/api/v1/storage/facilities", params={"near": "22.57,88.36"})).json()
    assert found["data"][0]["id"] == fac["id"]
    assert found["data"][0]["contact_email"] is None
    assert found["data"][0]["distance_km"] is not None
    none = await farmer.get("/api/v1/storage/facilities", params={"commodity": "jute"})
    assert none.json()["data"] == []
    roomy = await farmer.get("/api/v1/storage/facilities", params={"min_free_kg": 2000})
    assert roomy.json()["data"] == []
    assert (await farmer.post("/api/v1/storage/facilities", json={})).status_code == 403


async def test_booking_lifecycle_moves_capacity(make_user: UserFactory) -> None:
    op, _ = await make_user("storage_operator")
    farmer, _ = await make_user("farmer")
    fac = await _facility(op)
    zone = await op.post(
        f"/api/v1/storage/facilities/{fac['id']}/zones", json={"name": "Chamber A"}
    )
    assert zone.status_code == 201
    b = await _booking(farmer, fac["id"])
    assert b["facility"]["contact_email"] is None

    listed = (await op.get("/api/v1/storage/bookings")).json()["data"]
    assert [x["id"] for x in listed] == [b["id"]]
    assert listed[0]["farmer"]["email"] is None

    acc = await op.post(f"/api/v1/storage/bookings/{b['id']}/accept", json={})
    assert acc.status_code == 200, acc.text
    assert acc.json()["data"]["facility"]["contact_email"] == "store@example.org"
    assert acc.json()["data"]["farmer"]["email"] is not None
    f = await _fac_doc(fac["id"])
    assert (f["reserved_kg"], f["occupied_kg"]) == (300, 0)

    ci = await op.post(
        f"/api/v1/storage/bookings/{b['id']}/check-in", json={"zone_id": zone.json()["data"]["id"]}
    )
    assert ci.json()["data"]["status"] == "checked_in"
    assert ci.json()["data"]["zone_name"] == "Chamber A"
    f = await _fac_doc(fac["id"])
    assert (f["reserved_kg"], f["occupied_kg"]) == (0, 300)

    rel = await op.post(f"/api/v1/storage/bookings/{b['id']}/release", json={})
    assert rel.json()["data"]["status"] == "released"
    f = await _fac_doc(fac["id"])
    assert (f["reserved_kg"], f["occupied_kg"]) == (0, 0)

    assert mongo.db is not None
    actions = [a["action"] async for a in mongo.db.audit_logs.find().sort("created_at", 1)]
    assert actions == ["booking.accept", "booking.check-in", "booking.release"]


async def test_concurrent_accepts_never_exceed_capacity(make_user: UserFactory) -> None:
    op, _ = await make_user("storage_operator")
    farmer, _ = await make_user("farmer")
    fac = await _facility(op)  # 1000 kg
    bookings = [await _booking(farmer, fac["id"]) for _ in range(8)]  # 8 x 300 kg

    results = await asyncio.gather(
        *(op.post(f"/api/v1/storage/bookings/{b['id']}/accept", json={}) for b in bookings)
    )
    codes = sorted(r.status_code for r in results)
    assert codes.count(200) == 3, [r.text for r in results if r.status_code != 409]
    assert codes.count(409) == 5
    assert all(
        r.json()["error"]["code"] == "insufficient_capacity"
        for r in results
        if r.status_code == 409
    )
    f = await _fac_doc(fac["id"])
    assert f["reserved_kg"] == 900
    assert f["reserved_kg"] + f["occupied_kg"] <= f["capacity_kg"]
    assert mongo.db is not None
    assert await mongo.db.storage_bookings.count_documents({"status": "accepted"}) == 3
    assert await mongo.db.storage_bookings.count_documents({"status": "requested"}) == 5


async def test_cancel_accepted_releases_reservation(make_user: UserFactory) -> None:
    op, _ = await make_user("storage_operator")
    farmer, _ = await make_user("farmer")
    fac = await _facility(op)
    b = await _booking(farmer, fac["id"])
    await op.post(f"/api/v1/storage/bookings/{b['id']}/accept", json={})
    r = await farmer.post(f"/api/v1/storage/bookings/{b['id']}/cancel", json={})
    assert r.json()["data"]["status"] == "cancelled"
    assert (await _fac_doc(fac["id"]))["reserved_kg"] == 0


async def test_changes_requested_then_resubmit(make_user: UserFactory) -> None:
    op, _ = await make_user("storage_operator")
    farmer, _ = await make_user("farmer")
    fac = await _facility(op)
    b = await _booking(farmer, fac["id"])
    ch = await op.post(
        f"/api/v1/storage/bookings/{b['id']}/request-changes", json={"note": "Max 200 kg"}
    )
    assert ch.json()["data"]["status"] == "changes_requested"
    rs = await farmer.post(
        f"/api/v1/storage/bookings/{b['id']}/resubmit",
        json={"qty": "200", "unit": "kg", "start_date": "2027-01-10", "end_date": "2027-02-10"},
    )
    assert rs.json()["data"]["status"] == "requested"
    assert rs.json()["data"]["qty_kg"] == 200


async def test_booking_permissions(make_user: UserFactory) -> None:
    op, _ = await make_user("storage_operator")
    other_op, _ = await make_user("storage_operator")
    farmer, _ = await make_user("farmer")
    fac = await _facility(op)
    b = await _booking(farmer, fac["id"])
    assert (
        await other_op.post(f"/api/v1/storage/bookings/{b['id']}/accept", json={})
    ).status_code == 404
    assert (
        await farmer.post(f"/api/v1/storage/bookings/{b['id']}/accept", json={})
    ).status_code == 403
    assert (await op.post(f"/api/v1/storage/bookings/{b['id']}/cancel", json={})).status_code == 403
    assert (
        await other_op.patch(f"/api/v1/storage/facilities/{fac['id']}", json={"name": "x"})
    ).status_code == 404
    jute = await farmer.post(
        "/api/v1/storage/bookings",
        json={
            "facility_id": fac["id"],
            "commodity": "jute",
            "qty": "1",
            "unit": "kg",
            "start_date": "2027-01-10",
            "end_date": "2027-01-11",
        },
    )
    assert jute.status_code == 422


async def test_capacity_cannot_shrink_below_usage(make_user: UserFactory) -> None:
    op, _ = await make_user("storage_operator")
    farmer, _ = await make_user("farmer")
    fac = await _facility(op)
    b = await _booking(farmer, fac["id"], qty="600")
    await op.post(f"/api/v1/storage/bookings/{b['id']}/accept", json={})
    shrink = await op.patch(
        f"/api/v1/storage/facilities/{fac['id']}", json={"capacity": "500", "capacity_unit": "kg"}
    )
    assert shrink.status_code == 409
    grow = await op.patch(
        f"/api/v1/storage/facilities/{fac['id']}", json={"capacity": "2", "capacity_unit": "tonne"}
    )
    assert grow.json()["data"]["free_kg"] == 1400
