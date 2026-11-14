"""Security patch: headers, body size limits, correction bounds, per-IP login limit."""

import httpx
import pytest

from backend.app.core import ratelimit
from backend.app.core.ratelimit import RateLimiter
from backend.tests.conftest import UserFactory


async def test_security_headers_on_pages_and_api(client: httpx.AsyncClient) -> None:
    for path in ("/", "/api/v1/health"):
        r = await client.get(path)
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "same-origin"
        csp = r.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in csp
        assert "'unsafe-inline'" not in csp
    api = await client.get("/api/v1/health")
    assert api.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in api.headers  # only in production


async def test_docs_still_work_without_csp(client: httpx.AsyncClient) -> None:
    r = await client.get("/docs")
    assert r.status_code == 200
    assert "content-security-policy" not in r.headers
    assert r.headers["x-frame-options"] == "DENY"


async def test_declared_oversized_body_rejected(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/login",
        content=b"{" + b" " * (300 * 1024) + b"}",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


async def test_streamed_oversized_body_rejected(client: httpx.AsyncClient) -> None:
    async def chunks():  # no Content-Length → chunked
        for _ in range(40):
            yield b" " * 10_000

    r = await client.post(
        "/api/v1/auth/login", content=chunks(), headers={"content-type": "application/json"}
    )
    assert r.status_code == 413


@pytest.mark.usefixtures("test_db")
async def test_correction_values_are_bounded(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    farm = await farmer.post(
        "/api/v1/farms",
        json={"name": "P", "district": "Hooghly", "location": {"lat": 22.9, "lng": 88.39}},
    )
    batch = await farmer.post(
        "/api/v1/batches",
        json={
            "farm_id": farm.json()["data"]["id"],
            "commodity": "potato",
            "harvest_date": "2026-11-01",
            "qty": "1",
            "unit": "quintal",
        },
    )
    url = f"/api/v1/batches/{batch.json()['data']['id']}/events/0/correct"
    bad_bodies = [
        {"reason": "nested", "corrected": {"qty_kg": {"$gt": 1}}},
        {"reason": "too many", "corrected": {f"k{i}": i for i in range(11)}},
        {"reason": "bad key", "corrected": {"$set": 1}},
        {"reason": "long text", "corrected": {"note": "x" * 201}},
    ]
    for body in bad_bodies:
        assert (await farmer.post(url, json=body)).status_code == 422, body
    ok = await farmer.post(url, json={"reason": "reweighed", "corrected": {"qty_kg": 95}})
    assert ok.status_code == 200


@pytest.mark.usefixtures("test_db")
async def test_login_limited_per_ip_across_accounts(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ratelimit, "login_ip_limiter", RateLimiter(limit=3, window_s=60))
    codes = []
    for i in range(4):
        r = await client.post(
            "/api/v1/auth/login", json={"email": f"u{i}@example.org", "password": "wrong-pass"}
        )
        codes.append(r.status_code)
    assert codes == [401, 401, 401, 429]
