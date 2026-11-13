from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import APIRouter

from backend.app.core.errors import AppError
from backend.app.db.client import mongo
from backend.app.db.indexes import ensure_indexes
from backend.app.main import create_app

_probe = APIRouter(prefix="/api/v1")


@_probe.get("/_test/app-error")
async def _raise_app_error() -> None:
    raise AppError(409, "conflict_demo", "Something conflicted", {"field": "x"})


@_probe.get("/_test/crash")
async def _crash() -> None:
    raise RuntimeError("secret internals")


@_probe.get("/_test/validate")
async def _validate(n: int) -> dict[str, int]:
    return {"n": n}


# Separate app instance; probe routes go ahead of the catch-all static mount.
_probe_app = create_app()
_probe_app.router.routes[0:0] = _probe.routes


@pytest.fixture
async def probe_client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_probe_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _assert_envelope(body: dict[str, object], code: str) -> None:
    assert set(body) == {"error"}
    err = body["error"]
    assert isinstance(err, dict)
    assert set(err) == {"code", "message", "details"}
    assert err["code"] == code


async def test_health_without_db_reports_not_configured(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mongo, "client", None)
    monkeypatch.setattr(mongo, "db", None)
    r = await client.get("/api/v1/health")
    assert r.status_code == 503
    assert r.json()["data"] == {"status": "degraded", "db": "not_configured"}


async def test_health_ok_when_ping_succeeds(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ok() -> bool:
        return True

    monkeypatch.setattr(mongo, "client", object())
    monkeypatch.setattr(mongo, "ping", ok)
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"data": {"status": "ok", "db": "ok"}, "meta": {}}


async def test_unknown_api_route_uses_error_envelope(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    _assert_envelope(r.json(), "not_found")


async def test_app_error_envelope(probe_client: httpx.AsyncClient) -> None:
    r = await probe_client.get("/api/v1/_test/app-error")
    assert r.status_code == 409
    assert r.json() == {
        "error": {
            "code": "conflict_demo",
            "message": "Something conflicted",
            "details": {"field": "x"},
        }
    }


async def test_validation_error_envelope(probe_client: httpx.AsyncClient) -> None:
    r = await probe_client.get("/api/v1/_test/validate", params={"n": "abc"})
    assert r.status_code == 422
    _assert_envelope(r.json(), "validation_error")


async def test_unhandled_error_hides_internals(probe_client: httpx.AsyncClient) -> None:
    r = await probe_client.get("/api/v1/_test/crash")
    assert r.status_code == 500
    _assert_envelope(r.json(), "internal_error")
    assert "secret internals" not in r.text


async def test_static_index_served(client: httpx.AsyncClient) -> None:
    r = await client.get("/")
    assert r.status_code == 200
    assert "<title>Irminsul</title>" in r.text


@pytest.mark.usefixtures("test_db")
async def test_real_db_ping_and_indexes(client: httpx.AsyncClient) -> None:
    assert mongo.db is not None
    await ensure_indexes(mongo.db)  # idempotent
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["data"]["db"] == "ok"
