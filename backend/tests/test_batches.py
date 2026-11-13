"""M3 KrishiChain: batch followed creation → delivery, tampering detected (planning §12 M3)."""

from typing import Any

import httpx
import pytest
from bson import ObjectId

from backend.app.db.client import mongo
from backend.tests.conftest import UserFactory, _client

pytestmark = pytest.mark.usefixtures("test_db")
HOOGHLY = {"lat": 22.90, "lng": 88.39}


async def _farm(c: httpx.AsyncClient) -> str:
    r = await c.post(
        "/api/v1/farms", json={"name": "Plot", "district": "Hooghly", "location": HOOGHLY}
    )
    return r.json()["data"]["id"]


async def _batch(c: httpx.AsyncClient, farm_id: str, **kw: Any) -> dict[str, Any]:
    body = {
        "farm_id": farm_id,
        "commodity": "potato",
        "variety": "Jyoti",
        "harvest_date": "2026-11-01",
        "qty": "10",
        "unit": "quintal",
    } | kw
    r = await c.post("/api/v1/batches", json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _detail(c: httpx.AsyncClient, batch_id: str) -> dict[str, Any]:
    r = await c.get(f"/api/v1/batches/{batch_id}")
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _verify(c: httpx.AsyncClient, batch_id: str) -> dict[str, Any]:
    return (await c.get(f"/api/v1/batches/{batch_id}/verify")).json()["data"]


async def test_batch_followed_from_creation_to_delivery(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    dist, _ = await make_user("distributor", org_name="Ria Traders")
    farm_id = await _farm(farmer)
    batch = await _batch(farmer, farm_id)
    assert batch["batch_code"].startswith("IRM-26-")
    assert len(batch["batch_code"]) == 13
    assert batch["custodian"]["type"] == "farmer"

    listing = (
        await farmer.post(
            "/api/v1/listings",
            json={
                "farm_id": farm_id,
                "batch_id": batch["id"],
                "commodity": "potato",
                "qty": "10",
                "unit": "quintal",
                "available_from": "2026-11-02",
                "asking_price_per_quintal": "1200",
            },
        )
    ).json()["data"]
    assert listing["batch_id"] == batch["id"]

    req = (
        await dist.post(
            "/api/v1/purchase-requests",
            json={
                "listing_id": listing["id"],
                "qty": "1000",
                "unit": "kg",
                "price_per_quintal": "1200",
            },
        )
    ).json()["data"]
    order = (await farmer.post(f"/api/v1/purchase-requests/{req['id']}/accept")).json()["data"]
    assert order["batch_id"] == batch["id"]

    # Distributor can see the batch once linked by an order.
    assert (await dist.get(f"/api/v1/batches/{batch['id']}")).status_code == 200
    await farmer.post(f"/api/v1/orders/{order['id']}/dispatch", json={})
    mid = await _detail(farmer, batch["id"])
    assert mid["status"] == "in_transit"
    await dist.post(f"/api/v1/orders/{order['id']}/deliver", json={})

    final = await _detail(farmer, batch["id"])
    assert [e["type"] for e in final["events"]] == [
        "created",
        "listed",
        "request_accepted",
        "dispatched",
        "delivered",
    ]
    assert final["status"] == "delivered"
    assert final["custodian"] == {
        "type": "distributor",
        "id": final["custodian"]["id"],
        "name": "Ria Traders",
    }
    assert [e["seq"] for e in final["events"]] == [0, 1, 2, 3, 4]
    assert final["events"][1]["prev_hash"] == final["events"][0]["hash"]
    v = await _verify(farmer, batch["id"])
    assert v["valid"] is True
    assert v["events"] == 5


async def test_tampering_detected_by_verify(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    batch = await _batch(farmer, await _farm(farmer))
    assert mongo.db is not None
    # Someone edits the stored quantity directly in the database.
    await mongo.db.batch_events.update_one(
        {"batch_id": ObjectId(batch["id"]), "seq": 0}, {"$set": {"payload.qty_kg": 5}}
    )
    v = await _verify(farmer, batch["id"])
    assert v["valid"] is False
    assert v["first_invalid_seq"] == 0
    assert v["reason"] == "hash_mismatch"


async def test_deleting_latest_event_detected(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    farm_id = await _farm(farmer)
    batch = await _batch(farmer, farm_id)
    await farmer.post(
        "/api/v1/listings",
        json={
            "farm_id": farm_id,
            "batch_id": batch["id"],
            "commodity": "potato",
            "qty": "5",
            "unit": "quintal",
            "available_from": "2026-11-02",
            "asking_price_per_quintal": "1200",
        },
    )
    assert mongo.db is not None
    await mongo.db.batch_events.delete_one({"batch_id": ObjectId(batch["id"]), "seq": 1})
    v = await _verify(farmer, batch["id"])
    assert (v["valid"], v["reason"]) == (False, "head_mismatch")


async def test_storage_events_and_custody(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    op, _ = await make_user("storage_operator")
    other_op, _ = await make_user("storage_operator")
    batch = await _batch(farmer, await _farm(farmer), qty="500", unit="kg")
    fac = (
        await op.post(
            "/api/v1/storage/facilities",
            json={
                "name": "Chinsurah Cold",
                "district": "Hooghly",
                "location": {"lat": 22.88, "lng": 88.4},
                "commodities": ["potato"],
                "capacity": "2",
                "contact_phone": "9830000003",
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
                "qty": "500",
                "unit": "kg",
                "start_date": "2027-01-10",
                "end_date": "2027-02-10",
            },
        )
    ).json()["data"]
    assert b["batch_id"] == batch["id"]
    assert (await other_op.get(f"/api/v1/batches/{batch['id']}")).status_code == 404
    await op.post(f"/api/v1/storage/bookings/{b['id']}/accept", json={})
    await op.post(f"/api/v1/storage/bookings/{b['id']}/check-in", json={})

    d = await _detail(op, batch["id"])
    assert [e["type"] for e in d["events"]] == ["created", "booking_confirmed", "checked_in"]
    assert d["status"] == "in_storage"
    assert d["custodian"]["type"] == "facility"
    assert d["custodian"]["name"] == "Chinsurah Cold"

    await op.post(f"/api/v1/storage/bookings/{b['id']}/release", json={})
    d = await _detail(farmer, batch["id"])
    assert d["status"] == "active"
    assert d["custodian"]["type"] == "farmer"
    assert (await _verify(farmer, batch["id"]))["valid"] is True


async def test_correction_appends_without_overwriting(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    stranger, _ = await make_user("farmer")
    batch = await _batch(farmer, await _farm(farmer))
    r = await farmer.post(
        f"/api/v1/batches/{batch['id']}/events/0/correct",
        json={"reason": "Weighed again", "corrected": {"qty_kg": 980}},
    )
    assert r.status_code == 200, r.text
    events = r.json()["data"]["events"]
    assert events[0]["payload"]["qty_kg"] == 1000  # original untouched
    assert events[1]["type"] == "correction"
    assert events[1]["payload"]["ref_seq"] == 0
    assert events[1]["payload"]["corrected"] == {"qty_kg": 980}
    assert (await _verify(farmer, batch["id"]))["valid"] is True
    no = await stranger.post(
        f"/api/v1/batches/{batch['id']}/events/0/correct", json={"reason": "nope"}
    )
    assert no.status_code == 404
    missing = await farmer.post(
        f"/api/v1/batches/{batch['id']}/events/9/correct", json={"reason": "nope"}
    )
    assert missing.status_code == 404


async def test_split_creates_children_with_lineage(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    farm_id = await _farm(farmer)
    batch = await _batch(farmer, farm_id)  # 1000 kg
    too_much = await farmer.post(
        f"/api/v1/batches/{batch['id']}/split", json={"parts": ["600", "500"], "unit": "kg"}
    )
    assert too_much.status_code == 422
    r = await farmer.post(
        f"/api/v1/batches/{batch['id']}/split", json={"parts": ["6", "4"], "unit": "quintal"}
    )
    assert r.status_code == 200, r.text
    parent = r.json()["data"]
    assert parent["status"] == "split"
    assert [c["qty_kg"] for c in parent["children"]] == [600, 400]
    assert parent["events"][-1]["type"] == "split"

    child = await _detail(farmer, parent["children"][0]["id"])
    assert child["parent"]["batch_code"] == batch["batch_code"]
    assert child["events"][0]["payload"]["parent_code"] == batch["batch_code"]
    assert (await _verify(farmer, child["id"]))["valid"] is True
    assert (await _verify(farmer, batch["id"]))["valid"] is True
    again = await farmer.post(
        f"/api/v1/batches/{batch['id']}/split", json={"parts": ["1", "1"], "unit": "kg"}
    )
    assert again.status_code == 409
    listing = await farmer.post(
        "/api/v1/listings",
        json={
            "farm_id": farm_id,
            "batch_id": batch["id"],
            "commodity": "potato",
            "qty": "1",
            "unit": "kg",
            "available_from": "2026-11-02",
            "asking_price_per_quintal": "1",
        },
    )
    assert listing.status_code == 409  # closed parent cannot be listed
    assert listing.json()["error"]["code"] == "batch_closed"


async def test_qr_public_view_hides_personal_data(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer", name="Gopal Mondal")
    dist, _ = await make_user("distributor")
    batch = await _batch(farmer, await _farm(farmer))
    qr = (await farmer.get(f"/api/v1/batches/{batch['id']}/qr")).json()["data"]
    assert "/verify.html?t=" in qr["url"]
    assert qr["token"] not in batch["id"]
    again = (await farmer.get(f"/api/v1/batches/{batch['id']}/qr")).json()["data"]
    assert again["token"] == qr["token"]

    png = await farmer.get(f"/api/v1/batches/{batch['id']}/qr.png")
    assert png.headers["content-type"] == "image/png"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert (await dist.get(f"/api/v1/batches/{batch['id']}/qr")).status_code == 403

    async with _client() as anon:
        pub = await anon.get(f"/api/v1/qr/{qr['token']}")
    assert pub.status_code == 200
    data = pub.json()["data"]
    assert data["batch_code"] == batch["batch_code"]
    assert data["harvest_month"] == "2026-11"
    assert data["chain"]["valid"] is True
    text = pub.text
    assert "Gopal" not in text
    assert "+91" not in text
    assert "lat" not in text
    assert (await farmer.get("/api/v1/qr/not-a-token")).status_code == 404


async def test_batch_access_rules(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    other, _ = await make_user("farmer")
    dist, _ = await make_user("distributor")
    batch = await _batch(farmer, await _farm(farmer))
    assert (await other.get(f"/api/v1/batches/{batch['id']}")).status_code == 404
    assert (await dist.get(f"/api/v1/batches/{batch['id']}")).status_code == 404
    assert (await dist.post("/api/v1/batches", json={})).status_code == 403
    future = await farmer.post(
        "/api/v1/batches",
        json={
            "farm_id": await _farm(farmer),
            "commodity": "rice",
            "harvest_date": "2099-01-01",
            "qty": "1",
            "unit": "kg",
        },
    )
    assert future.status_code == 422
    assert len((await farmer.get("/api/v1/batches")).json()["data"]) == 1
