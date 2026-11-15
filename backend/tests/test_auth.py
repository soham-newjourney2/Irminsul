"""M1: auth, pending gate, RBAC, admin approval + audit."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
import pytest
from fastapi import APIRouter, Depends

from backend.app.core.deps import require_role
from backend.app.core.security import hash_password
from backend.app.db.client import Doc, mongo
from backend.app.main import create_app

pytestmark = pytest.mark.usefixtures("test_db")

PASSWORD = "correct-horse-1"  # noqa: S105 — test fixture only

# Probe app: one endpoint per role, placed ahead of the static mount.
_probe = APIRouter(prefix="/api/v1/_probe")
for _role in ("farmer", "distributor", "storage_operator", "admin"):

    def _make(role: str) -> None:
        @_probe.get(f"/{role}")
        async def _ep(user: Annotated[Doc, Depends(require_role(role))]) -> dict[str, str]:
            return {"role": user["role"]}

    _make(_role)

_app = create_app()
_app.router.routes[0:0] = _probe.routes


@pytest.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _reg(email: str, role: str, **extra: Any) -> dict[str, Any]:
    body = {"email": email, "password": PASSWORD, "name": f"{role} user", "role": role}
    return body | extra


async def _register(api: httpx.AsyncClient, email: str, role: str, **extra: Any) -> dict[str, Any]:
    r = await api.post("/api/v1/auth/register", json=_reg(email, role, **extra))
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _login(api: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await api.post("/api/v1/auth/login", json={"email": email, "password": password})


async def _make_admin(api: httpx.AsyncClient, email: str = "admin@example.org") -> None:
    assert mongo.db is not None
    now = datetime.now(UTC)
    await mongo.db.users.insert_one(
        {
            "schema_version": 1,
            "email": email,
            "name": "Admin",
            "role": "admin",
            "status": "active",
            "language": "en",
            "password_hash": await hash_password(PASSWORD),
            "org_id": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    api.cookies.clear()
    assert (await _login(api, email)).status_code == 200


# --- registration / login -------------------------------------------------


async def test_farmer_register_is_active_and_logged_in(api: httpx.AsyncClient) -> None:
    data = await _register(api, "  Gopal.Mondal@Example.ORG ", "farmer", org_name="ignored")
    assert data["email"] == "gopal.mondal@example.org"
    assert data["status"] == "active"
    assert data["org"] is None
    me = await api.get("/api/v1/users/me")
    assert me.status_code == 200
    assert me.json()["data"]["role"] == "farmer"
    assert "password_hash" not in me.text


async def test_distributor_register_is_pending_with_org(api: httpx.AsyncClient) -> None:
    data = await _register(api, "u00001@example.org", "distributor", org_name="Hooghly Traders")
    assert data["status"] == "pending"
    assert data["org"]["name"] == "Hooghly Traders"
    assert data["org"]["status"] == "pending"
    assert mongo.db is not None
    assert await mongo.db.memberships.count_documents({}) == 1


async def test_pending_role_requires_org_name(api: httpx.AsyncClient) -> None:
    r = await api.post("/api/v1/auth/register", json=_reg("u00002@example.org", "storage_operator"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "email",
    [
        "not-an-email",
        "a@b",
        "a@@b.com",
        "a..b@example.com",
        ".a@example.com",
        "a@-x.com",
        "x" * 250 + "@ex.com",
        "a b@example.com",
    ],
)
async def test_invalid_email_rejected(api: httpx.AsyncClient, email: str) -> None:
    r = await api.post("/api/v1/auth/register", json=_reg(email, "farmer"))
    assert r.status_code == 422


async def test_cannot_self_register_as_admin(api: httpx.AsyncClient) -> None:
    r = await api.post("/api/v1/auth/register", json=_reg("u00003@example.org", "admin"))
    assert r.status_code == 422


async def test_duplicate_email_conflict(api: httpx.AsyncClient) -> None:
    await _register(api, "u00004@example.org", "farmer")
    r = await api.post("/api/v1/auth/register", json=_reg("U00004@EXAMPLE.org", "farmer"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


async def test_login_and_wrong_password(api: httpx.AsyncClient) -> None:
    await _register(api, "u00005@example.org", "farmer")
    api.cookies.clear()
    bad = await _login(api, "u00005@example.org", "wrong-password")
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_credentials"
    unknown = await _login(api, "nobody@example.org")
    assert unknown.status_code == 401
    assert unknown.json()["error"]["code"] == "invalid_credentials"
    ok = await _login(api, "u00005@example.org")
    assert ok.status_code == 200
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


async def test_logout_clears_session(api: httpx.AsyncClient) -> None:
    await _register(api, "u00006@example.org", "farmer")
    assert (await api.post("/api/v1/auth/logout")).status_code == 204
    r = await api.get("/api/v1/users/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


async def test_me_without_cookie_and_with_garbage_cookie(api: httpx.AsyncClient) -> None:
    assert (await api.get("/api/v1/users/me")).status_code == 401
    api.cookies.set("irminsul_session", "not-a-jwt")
    assert (await api.get("/api/v1/users/me")).status_code == 401


async def test_login_rate_limited_after_five_attempts(api: httpx.AsyncClient) -> None:
    await _register(api, "u00007@example.org", "farmer")
    for _ in range(5):
        assert (await _login(api, "u00007@example.org", "wrong-password")).status_code == 401
    r = await _login(api, "u00007@example.org")
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"


async def test_update_language(api: httpx.AsyncClient) -> None:
    await _register(api, "u00008@example.org", "farmer")
    r = await api.patch("/api/v1/users/me", json={"language": "bn"})
    assert r.status_code == 200
    assert r.json()["data"]["language"] == "bn"
    assert (await api.patch("/api/v1/users/me", json={"language": "fr"})).status_code == 422


# --- pending gate + RBAC --------------------------------------------------


async def test_pending_user_blocked_from_role_endpoints(api: httpx.AsyncClient) -> None:
    await _register(api, "u00009@example.org", "distributor", org_name="Acme")
    me = await api.get("/api/v1/users/me")
    assert me.status_code == 200  # can see own status
    r = await api.get("/api/v1/_probe/distributor")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "account_pending"


@pytest.mark.parametrize("role", ["farmer", "distributor", "storage_operator", "admin"])
async def test_each_role_reaches_only_its_endpoint(api: httpx.AsyncClient, role: str) -> None:
    if role == "admin":
        await _make_admin(api)
    else:
        await _register(api, "u00010@example.org", role, org_name="Org")
        assert mongo.db is not None
        await mongo.db.users.update_one({"role": role}, {"$set": {"status": "active"}})
    for target in ("farmer", "distributor", "storage_operator", "admin"):
        r = await api.get(f"/api/v1/_probe/{target}")
        if target == role:
            assert r.status_code == 200, (role, target, r.text)
        else:
            assert r.status_code == 403, (role, target)
            assert r.json()["error"]["code"] == "forbidden"


async def test_non_admin_denied_admin_api(api: httpx.AsyncClient) -> None:
    await _register(api, "u00011@example.org", "farmer")
    assert (await api.get("/api/v1/admin/users")).status_code == 403
    assert (await api.get("/api/v1/admin/audit-logs")).status_code == 403
    api.cookies.clear()
    assert (await api.get("/api/v1/admin/users")).status_code == 401


# --- admin approval + audit -----------------------------------------------


async def test_admin_approves_pending_user_with_audit(api: httpx.AsyncClient) -> None:
    pending = await _register(api, "u00012@example.org", "storage_operator", org_name="Cold Co")
    await _make_admin(api)

    listed = await api.get("/api/v1/admin/users", params={"status": "pending"})
    assert [u["id"] for u in listed.json()["data"]] == [pending["id"]]

    r = await api.post(f"/api/v1/admin/users/{pending['id']}/approve")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "active"
    assert r.json()["data"]["org"]["status"] == "active"

    again = await api.post(f"/api/v1/admin/users/{pending['id']}/approve")
    assert again.status_code == 409

    logs = (await api.get("/api/v1/admin/audit-logs")).json()["data"]
    assert len(logs) == 1
    assert logs[0]["action"] == "user.approve"
    assert logs[0]["target_id"] == pending["id"]

    api.cookies.clear()
    assert (await _login(api, "u00012@example.org")).status_code == 200
    assert (await api.get("/api/v1/_probe/storage_operator")).status_code == 200


async def test_admin_rejects_pending_user(api: httpx.AsyncClient) -> None:
    pending = await _register(api, "u00013@example.org", "distributor", org_name="X")
    stale_cookie = api.cookies.get("irminsul_session")
    await _make_admin(api)
    r = await api.post(f"/api/v1/admin/users/{pending['id']}/reject", json={"reason": "No docs"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "rejected"

    logs = (await api.get("/api/v1/admin/audit-logs")).json()["data"]
    assert logs[0]["action"] == "user.reject"
    assert logs[0]["details"]["reason"] == "No docs"

    api.cookies.clear()
    login = await _login(api, "u00013@example.org")
    assert login.status_code == 403
    assert login.json()["error"]["code"] == "account_rejected"
    assert stale_cookie is not None
    api.cookies.set("irminsul_session", stale_cookie)
    assert (await api.get("/api/v1/users/me")).status_code == 401


async def test_approve_unknown_or_invalid_id(api: httpx.AsyncClient) -> None:
    await _make_admin(api)
    assert (await api.post("/api/v1/admin/users/not-an-id/approve")).status_code == 404
    missing = "0123456789abcdef01234567"
    assert (await api.post(f"/api/v1/admin/users/{missing}/approve")).status_code == 404


@pytest.mark.parametrize(
    ("raw", "normalised"),
    [
        ("Gopal@Example.org", "gopal@example.org"),
        ("first.last+tag@mail.example.co.in", "first.last+tag@mail.example.co.in"),
        ("  x_y-z@sub-domain.example.com ", "x_y-z@sub-domain.example.com"),
    ],
)
def test_normalize_email_accepts_real_addresses(raw: str, normalised: str) -> None:
    from backend.app.modules.users.schemas import normalize_email

    assert normalize_email(raw) == normalised


async def test_obsolete_phone_index_is_dropped(api: httpx.AsyncClient) -> None:
    from backend.app.db.indexes import ensure_indexes

    assert mongo.db is not None
    await mongo.db.users.create_index("phone", unique=True, name="phone_unique")
    await ensure_indexes(mongo.db)
    names = {i["name"] async for i in await mongo.db.users.list_indexes()}
    assert "phone_unique" not in names
    assert "email_unique" in names
    # Two accounts without any phone field must both be allowed.
    await _register(api, "one@example.org", "farmer")
    await _register(api, "two@example.org", "farmer")


@pytest.mark.parametrize(
    "email", ["x?subject=hi@example.com", "a&b@example.com", "a=b@example.com"]
)
async def test_email_rejects_mailto_injection(api: httpx.AsyncClient, email: str) -> None:
    r = await api.post("/api/v1/auth/register", json=_reg(email, "farmer"))
    assert r.status_code == 422
