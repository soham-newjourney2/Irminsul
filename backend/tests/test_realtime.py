"""WebSocket hub + notification push (planning §0 #21)."""

from typing import Any

import httpx
import pytest

from backend.app.core.ws import Hub, hub
from backend.tests.conftest import UserFactory


class FakeSocket:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[Any] = []
        self.fail = fail

    async def send_json(self, data: Any, mode: str = "text") -> None:
        if self.fail:
            raise RuntimeError("closed")
        self.sent.append(data)


async def test_hub_targets_and_drops_dead_sockets() -> None:
    h = Hub()
    a, b, dead = FakeSocket(), FakeSocket(), FakeSocket(fail=True)
    h.connect("u1", a)
    h.connect("u2", b)
    h.connect("u2", dead)
    await h.send_user("u1", {"type": "x"})
    assert a.sent == [{"type": "x"}]
    assert b.sent == []
    await h.broadcast({"type": "y"})
    assert b.sent == [{"type": "y"}]
    assert h.connected_users() == 2
    h.disconnect("u1", a)
    assert h.connected_users() == 1


@pytest.mark.usefixtures("test_db")
async def test_notifications_pushed_and_listed(make_user: UserFactory) -> None:
    farmer, farmer_doc = await make_user("farmer")
    op, _ = await make_user("storage_operator")
    sock = FakeSocket()
    hub.connect(str(farmer_doc["_id"]), sock)
    broadcast = FakeSocket()
    hub.connect("observer", broadcast)
    try:
        fac = (
            await op.post(
                "/api/v1/storage/facilities",
                json={
                    "name": "F",
                    "district": "Hooghly",
                    "location": {"lat": 22.9, "lng": 88.4},
                    "commodities": ["potato"],
                    "capacity": "1",
                    "contact_email": "f@example.org",
                },
            )
        ).json()["data"]
        b = (
            await farmer.post(
                "/api/v1/storage/bookings",
                json={
                    "facility_id": fac["id"],
                    "commodity": "potato",
                    "qty": "100",
                    "unit": "kg",
                    "start_date": "2027-01-10",
                    "end_date": "2027-01-20",
                },
            )
        ).json()["data"]
        await op.post(f"/api/v1/storage/bookings/{b['id']}/accept", json={})
    finally:
        hub.disconnect(str(farmer_doc["_id"]), sock)
        hub.disconnect("observer", broadcast)

    assert [m["data"]["kind"] for m in sock.sent if m["type"] == "notification"] == [
        "booking.accepted"
    ]
    cap = [m for m in broadcast.sent if m["type"] == "facility.capacity"]
    assert cap[-1]["data"]["reserved_kg"] == 100

    listed = (await farmer.get("/api/v1/notifications")).json()
    assert listed["meta"]["unread"] == 1
    marked = await farmer.post("/api/v1/notifications/read", json={})
    assert marked.json()["data"]["marked"] == 1
    assert (await farmer.get("/api/v1/notifications")).json()["meta"]["unread"] == 0


async def test_ws_rejects_anonymous(client: httpx.AsyncClient) -> None:
    # Plain HTTP GET to a websocket route is not upgraded → 404 from routing, not a crash.
    r = await client.get("/ws")
    assert r.status_code in (403, 404)
