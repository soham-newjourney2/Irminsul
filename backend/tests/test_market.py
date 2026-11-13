"""M2 marketplace: farms, listings, purchase requests, orders (planning §4.1, §13)."""

from typing import Any

import httpx
import pytest

from backend.app.db.client import mongo
from backend.tests.conftest import UserFactory

pytestmark = pytest.mark.usefixtures("test_db")

HOOGHLY = {"lat": 22.90, "lng": 88.39}
KOLKATA = "22.57,88.36"


async def _farm(c: httpx.AsyncClient, **kw: Any) -> str:
    body = {"name": "North plot", "district": "hooghly", "location": HOOGHLY} | kw
    r = await c.post("/api/v1/farms", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["data"]["district"] == "Hooghly"
    return r.json()["data"]["id"]


async def _listing(c: httpx.AsyncClient, farm_id: str, **kw: Any) -> dict[str, Any]:
    body = {
        "farm_id": farm_id,
        "commodity": "potato",
        "variety": "Jyoti",
        "qty": "10",
        "unit": "quintal",
        "available_from": "2026-11-01",
        "asking_price_per_quintal": "1200",
    } | kw
    r = await c.post("/api/v1/listings", json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _request(c: httpx.AsyncClient, listing_id: str, **kw: Any) -> dict[str, Any]:
    body = {"listing_id": listing_id, "qty": "400", "unit": "kg", "price_per_quintal": "1100"} | kw
    r = await c.post("/api/v1/purchase-requests", json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _listing_doc(listing_id: str) -> dict[str, Any]:
    assert mongo.db is not None
    from bson import ObjectId

    doc = await mongo.db.produce_listings.find_one({"_id": ObjectId(listing_id)})
    assert doc is not None
    return doc


async def test_listing_create_units_and_search(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    dist, _ = await make_user("distributor")
    listing = await _listing(farmer, await _farm(farmer))
    assert listing["qty_kg"] == 1000
    assert listing["remaining_kg"] == 1000
    assert listing["display_unit"] == "quintal"
    assert listing["asking_price_paise_per_quintal"] == 120000
    assert listing["status"] == "active"
    assert listing["farmer"]["phone"] is None

    near = await dist.get("/api/v1/listings", params={"near": KOLKATA, "radius_km": 60})
    rows = near.json()["data"]
    assert [x["id"] for x in rows] == [listing["id"]]
    assert 30 < rows[0]["distance_km"] < 45
    assert rows[0]["farmer"]["phone"] is None
    far = await dist.get("/api/v1/listings", params={"near": KOLKATA, "radius_km": 10})
    assert far.json()["data"] == []
    other = await dist.get("/api/v1/listings", params={"commodity": "rice"})
    assert other.json()["data"] == []


async def test_drafts_hidden_and_publish(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    dist, _ = await make_user("distributor")
    draft = await _listing(farmer, await _farm(farmer), publish=False)
    assert draft["status"] == "draft"
    assert (await dist.get("/api/v1/listings")).json()["data"] == []
    assert (await dist.get(f"/api/v1/listings/{draft['id']}")).status_code == 404
    r = await farmer.post(f"/api/v1/listings/{draft['id']}/publish")
    assert r.json()["data"]["status"] == "active"
    assert len((await dist.get("/api/v1/listings")).json()["data"]) == 1


async def test_rbac_and_ownership(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    other_farmer, _ = await make_user("farmer")
    dist, _ = await make_user("distributor")
    pending, _ = await make_user("distributor", status="pending")
    farm_id = await _farm(farmer)
    listing = await _listing(farmer, farm_id)

    assert (await dist.post("/api/v1/farms", json={})).status_code == 403
    r = await other_farmer.post("/api/v1/listings", json={"farm_id": farm_id})
    assert r.status_code == 422  # body invalid before ownership
    bad = await other_farmer.post(
        "/api/v1/listings",
        json={
            "farm_id": farm_id,
            "commodity": "potato",
            "qty": "1",
            "unit": "kg",
            "available_from": "2026-11-01",
            "asking_price_per_quintal": "1",
        },
    )
    assert bad.status_code == 404  # someone else's farm
    edit = await other_farmer.patch(f"/api/v1/listings/{listing['id']}", json={"note": "x"})
    assert edit.status_code == 404
    req = await farmer.post(
        "/api/v1/purchase-requests",
        json={"listing_id": listing["id"], "qty": "1", "unit": "kg", "price_per_quintal": "1"},
    )
    assert req.status_code == 403
    blocked = await pending.get("/api/v1/listings")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "account_pending"


async def test_request_counter_accept_creates_order(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer", name="Gopal")
    dist, _ = await make_user("distributor", name="Ria", org_name="Ria Traders")
    listing = await _listing(farmer, await _farm(farmer))
    req = await _request(dist, listing["id"])
    assert req["status"] == "pending"
    assert req["awaiting"] == "farmer"

    inbox = (await farmer.get("/api/v1/purchase-requests")).json()["data"]
    assert inbox[0]["counterparty"]["org_name"] == "Ria Traders"
    assert inbox[0]["counterparty"]["phone"] is None  # not revealed before acceptance

    # Distributor cannot accept own offer; farmer counters on price.
    assert (await dist.post(f"/api/v1/purchase-requests/{req['id']}/accept")).status_code == 409
    c = await farmer.post(
        f"/api/v1/purchase-requests/{req['id']}/counter", json={"price_per_quintal": "1150"}
    )
    assert c.json()["data"]["status"] == "countered"
    assert c.json()["data"]["awaiting"] == "distributor"
    assert (await farmer.post(f"/api/v1/purchase-requests/{req['id']}/accept")).status_code == 409

    r = await dist.post(f"/api/v1/purchase-requests/{req['id']}/accept")
    assert r.status_code == 200, r.text
    order = r.json()["data"]
    assert order["status"] == "confirmed"
    assert order["qty_kg"] == 400
    assert order["agreed_price_paise_per_quintal"] == 115000
    assert order["total_paise"] == 460000  # 4 q x Rs 1,150
    assert order["farmer"]["phone"] is not None
    assert order["distributor"]["phone"] is not None

    doc = await _listing_doc(listing["id"])
    assert doc["remaining_kg"] == 600
    assert doc["status"] == "partially_fulfilled"

    hist = (await dist.get(f"/api/v1/purchase-requests/{req['id']}")).json()["data"]
    assert [h["action"] for h in hist["history"]] == ["offer", "counter", "accept"]
    assert hist["counterparty"]["phone"] is not None

    assert mongo.db is not None
    kinds = {n["kind"] async for n in mongo.db.notifications.find()}
    assert {"request.created", "request.countered", "request.accepted"} <= kinds
    audits = [a["action"] async for a in mongo.db.audit_logs.find()]
    assert audits == ["order.create"]


async def test_insufficient_quantity_rolls_back(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    dist1, _ = await make_user("distributor")
    dist2, _ = await make_user("distributor")
    listing = await _listing(farmer, await _farm(farmer))
    r1 = await _request(dist1, listing["id"], qty="7", unit="quintal")
    r2 = await _request(dist2, listing["id"], qty="7", unit="quintal")

    assert (await farmer.post(f"/api/v1/purchase-requests/{r1['id']}/accept")).status_code == 200
    second = await farmer.post(f"/api/v1/purchase-requests/{r2['id']}/accept")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "insufficient_quantity"

    # Transaction rolled back: request still pending, no second order, remaining intact.
    again = (await dist2.get(f"/api/v1/purchase-requests/{r2['id']}")).json()["data"]
    assert again["status"] == "pending"
    assert mongo.db is not None
    assert await mongo.db.orders.count_documents({}) == 1
    assert (await _listing_doc(listing["id"]))["remaining_kg"] == 300


async def test_order_lifecycle_and_listing_status(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    dist, _ = await make_user("distributor")
    listing = await _listing(farmer, await _farm(farmer), qty="1", unit="tonne")
    req = await _request(dist, listing["id"], qty="1000")
    order = (await farmer.post(f"/api/v1/purchase-requests/{req['id']}/accept")).json()["data"]
    assert (await _listing_doc(listing["id"]))["status"] == "reserved"

    oid = order["id"]
    assert (await dist.post(f"/api/v1/orders/{oid}/dispatch", json={})).status_code == 403
    assert (await farmer.post(f"/api/v1/orders/{oid}/deliver", json={})).status_code == 403
    assert (await farmer.post(f"/api/v1/orders/{oid}/dispatch", json={})).status_code == 200
    cancel = await farmer.post(f"/api/v1/orders/{oid}/cancel", json={})
    assert cancel.status_code == 409  # dispatched orders cannot be cancelled by parties
    assert (await dist.post(f"/api/v1/orders/{oid}/deliver", json={})).status_code == 200
    assert (await _listing_doc(listing["id"]))["status"] == "sold"
    closed = await dist.post(f"/api/v1/orders/{oid}/close", json={"note": "Paid in cash"})
    assert closed.json()["data"]["status"] == "closed"
    assert [h["status"] for h in closed.json()["data"]["history"]] == [
        "confirmed",
        "dispatched",
        "delivered",
        "closed",
    ]


async def test_order_cancel_restores_quantity(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    dist, _ = await make_user("distributor")
    listing = await _listing(farmer, await _farm(farmer))
    req = await _request(dist, listing["id"], qty="10", unit="quintal")
    order = (await farmer.post(f"/api/v1/purchase-requests/{req['id']}/accept")).json()["data"]
    assert (await _listing_doc(listing["id"]))["status"] == "reserved"
    r = await dist.post(f"/api/v1/orders/{order['id']}/cancel", json={"note": "Truck broke"})
    assert r.json()["data"]["status"] == "cancelled"
    doc = await _listing_doc(listing["id"])
    assert doc["remaining_kg"] == 1000
    assert doc["status"] == "active"


async def test_visibility_of_requests_and_orders(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    stranger_farmer, _ = await make_user("farmer")
    dist, _ = await make_user("distributor")
    stranger_dist, _ = await make_user("distributor")
    listing = await _listing(farmer, await _farm(farmer))
    req = await _request(dist, listing["id"])
    assert (await stranger_farmer.get(f"/api/v1/purchase-requests/{req['id']}")).status_code == 404
    assert (await stranger_dist.get("/api/v1/purchase-requests")).json()["data"] == []
    order = (await farmer.post(f"/api/v1/purchase-requests/{req['id']}/accept")).json()["data"]
    assert (await stranger_dist.get(f"/api/v1/orders/{order['id']}")).status_code == 404
    cancel = await stranger_farmer.post(f"/api/v1/orders/{order['id']}/cancel", json={})
    assert cancel.status_code == 404


async def test_reject_withdraw_rules(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    dist, _ = await make_user("distributor")
    listing = await _listing(farmer, await _farm(farmer))
    r1 = await _request(dist, listing["id"])
    assert (
        await dist.post(f"/api/v1/purchase-requests/{r1['id']}/reject", json={})
    ).status_code == 403
    rej = await farmer.post(f"/api/v1/purchase-requests/{r1['id']}/reject", json={"note": "Low"})
    assert rej.json()["data"]["status"] == "rejected"
    r2 = await _request(dist, listing["id"])
    assert (
        await farmer.post(f"/api/v1/purchase-requests/{r2['id']}/withdraw", json={})
    ).status_code == 403
    wd = await dist.post(f"/api/v1/purchase-requests/{r2['id']}/withdraw", json={})
    assert wd.json()["data"]["status"] == "withdrawn"
    too_much = await dist.post(
        "/api/v1/purchase-requests",
        json={
            "listing_id": listing["id"],
            "qty": "11",
            "unit": "quintal",
            "price_per_quintal": "1",
        },
    )
    assert too_much.status_code == 409


async def test_listing_cancel_rejects_open_requests(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    dist, _ = await make_user("distributor")
    listing = await _listing(farmer, await _farm(farmer))
    req = await _request(dist, listing["id"])
    r = await farmer.post(f"/api/v1/listings/{listing['id']}/cancel")
    assert r.json()["data"]["status"] == "cancelled"
    got = (await dist.get(f"/api/v1/purchase-requests/{req['id']}")).json()["data"]
    assert got["status"] == "rejected"
    assert (await dist.get("/api/v1/listings")).json()["data"] == []


async def test_idempotent_listing_create(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    farm_id = await _farm(farmer)
    body = {
        "farm_id": farm_id,
        "commodity": "tomato",
        "qty": "50",
        "unit": "kg",
        "available_from": "2026-11-01",
        "asking_price_per_quintal": "2000",
    }
    headers = {"Idempotency-Key": "abc-123"}
    a = await farmer.post("/api/v1/listings", json=body, headers=headers)
    b = await farmer.post("/api/v1/listings", json=body, headers=headers)
    assert a.status_code == b.status_code == 201
    assert a.json()["data"]["id"] == b.json()["data"]["id"]
    assert mongo.db is not None
    assert await mongo.db.produce_listings.count_documents({}) == 1


async def test_invalid_inputs(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    outside = await farmer.post(
        "/api/v1/farms",
        json={"name": "x", "district": "Hooghly", "location": {"lat": 28.6, "lng": 77.2}},
    )
    assert outside.status_code == 422
    unknown = await farmer.post(
        "/api/v1/farms", json={"name": "x", "district": "Atlantis", "location": HOOGHLY}
    )
    assert unknown.status_code == 422
    farm_id = await _farm(farmer)
    bad_unit = await farmer.post(
        "/api/v1/listings",
        json={
            "farm_id": farm_id,
            "commodity": "potato",
            "qty": "5",
            "unit": "maund",
            "available_from": "2026-11-01",
            "asking_price_per_quintal": "1000",
        },
    )
    assert bad_unit.status_code == 422
    bad_near = await farmer.get("/api/v1/listings", params={"near": "abc"})
    assert bad_near.status_code == 422
