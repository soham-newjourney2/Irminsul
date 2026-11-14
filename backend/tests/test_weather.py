"""Weather client, advisory engine (pure), and API with a mocked provider."""

from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest

from backend.app.core.errors import AppError
from backend.app.integrations import open_meteo
from backend.app.modules.weather import engine, service
from backend.tests.conftest import UserFactory

NOW = datetime(2026, 11, 14, 6, 0)


def _forecast(temp: float, rh: float, rain: float = 0.0, daily_rain: float = 0.0) -> dict[str, Any]:
    start = NOW.replace(hour=0)
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(72)]
    days = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
    return {
        "timezone": "Asia/Kolkata",
        "hourly": {
            "time": times,
            "temperature_2m": [temp] * 72,
            "relative_humidity_2m": [rh] * 72,
            "precipitation": [rain] * 72,
        },
        "daily": {
            "time": days,
            "precipitation_sum": [daily_rain, 0.0, 0.0],
            "temperature_2m_max": [temp + 3] * 3,
            "temperature_2m_min": [temp - 3] * 3,
        },
        "fetched_at": "2026-11-14T00:30:00+00:00",
    }


RULES = engine.load_rules()


def test_every_rule_cites_a_source() -> None:
    for rule in RULES:
        assert rule["source"]["urls"], rule["id"]
        assert rule["source"]["quote"], rule["id"]
        assert "verified" in rule
        assert rule["assumptions"], rule["id"]


def test_cool_wet_weather_flags_potato_late_blight() -> None:
    out = engine.evaluate(_forecast(temp=18, rh=95), ["potato"], NOW, RULES)
    ids = {a.rule_id for a in out}
    assert "potato_late_blight_risk" in ids
    a = next(a for a in out if a.rule_id == "potato_late_blight_risk")
    assert a.evidence["matching_hours"] == 48
    assert a.verified is True
    assert a.source["urls"][0].startswith("https://agritech.tnau.ac.in/")


def test_dry_weather_gives_no_disease_advisory() -> None:
    assert engine.evaluate(_forecast(temp=18, rh=40), ["potato", "tomato"], NOW, RULES) == []


def test_crop_filter() -> None:
    out = engine.evaluate(_forecast(temp=20, rh=95), ["tomato"], NOW, RULES)
    assert {a.crop for a in out} == {"tomato"}


def test_rain_required_for_early_blight_rules() -> None:
    dry = engine.evaluate(_forecast(temp=27, rh=85, rain=0.0), ["tomato"], NOW, RULES)
    wet = engine.evaluate(_forecast(temp=27, rh=85, rain=0.2), ["tomato"], NOW, RULES)
    assert "tomato_early_blight_risk" not in {a.rule_id for a in dry}
    assert "tomato_early_blight_risk" in {a.rule_id for a in wet}


@pytest.mark.parametrize(
    ("mm", "label"),
    [(50.0, None), (64.5, "heavy"), (120.0, "very_heavy"), (210.0, "extremely_heavy")],
)
def test_heavy_rain_bands(mm: float, label: str | None) -> None:
    out = [
        a
        for a in engine.evaluate(_forecast(25, 50, daily_rain=mm), [], NOW, RULES)
        if a.rule_id == "heavy_rain"
    ]
    if label is None:
        assert out == []
    else:
        assert out[0].label == label
        assert out[0].verified is False  # IMD threshold awaits owner confirmation


async def test_open_meteo_client_validates_shape() -> None:
    good = _forecast(20, 60)
    good.pop("fetched_at")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["timezone"] == "Asia/Kolkata"
        assert "relative_humidity_2m" in request.url.params["hourly"]
        return httpx.Response(200, json=good)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        data = await open_meteo.fetch_forecast(22.9, 88.4, client=c)
    assert "fetched_at" in data

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    ) as c:
        with pytest.raises(open_meteo.WeatherUnavailable):
            await open_meteo.fetch_forecast(22.9, 88.4, client=c)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(502))) as c:
        with pytest.raises(open_meteo.WeatherUnavailable):
            await open_meteo.fetch_forecast(22.9, 88.4, client=c)


def test_guidance_lookup() -> None:
    g = service.guidance("potato.late_blight")
    assert g.review_status == "not expert-reviewed"
    assert g.entry["sources"][0]["url"].startswith("https://")
    with pytest.raises(AppError):
        service.guidance("tomato.leaf_mold")  # deliberately not covered


# --- API (needs DB) -----------------------------------------------------------------


@pytest.mark.usefixtures("test_db")
async def test_weather_api_caches_and_serves_stale(
    make_user: UserFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}
    healthy = {"ok": True}

    async def fake_fetch(lat: float, lng: float, **_: Any) -> dict[str, Any]:
        calls["n"] += 1
        if not healthy["ok"]:
            raise open_meteo.WeatherUnavailable("down")
        return _forecast(18, 95)

    monkeypatch.setattr(open_meteo, "fetch_forecast", fake_fetch)
    farmer, _ = await make_user("farmer")
    farm = await farmer.post(
        "/api/v1/farms",
        json={"name": "P", "district": "Hooghly", "location": {"lat": 22.9, "lng": 88.39}},
    )
    fid = farm.json()["data"]["id"]
    first = await farmer.get("/api/v1/weather", params={"farm_id": fid})
    assert first.status_code == 200, first.text
    assert first.json()["data"]["cached"] is False
    assert first.json()["data"]["attribution"].startswith("Weather data by Open-Meteo")
    second = await farmer.get("/api/v1/weather", params={"farm_id": fid})
    assert second.json()["data"]["cached"] is True
    assert calls["n"] == 1

    adv = await farmer.get("/api/v1/advisories", params={"farm_id": fid, "crops": "potato"})
    assert adv.status_code == 200
    rows = adv.json()["data"]
    assert rows[0]["rule_id"] == "potato_late_blight_risk"
    assert rows[0]["guidance_key"] == "potato.late_blight"

    # Provider down + expired cache → stale data, clearly flagged.
    from backend.app.db.client import mongo

    assert mongo.db is not None
    await mongo.db.weather_cache.update_many({}, {"$set": {"fetched_at": datetime(2020, 1, 1)}})
    healthy["ok"] = False
    stale = await farmer.get("/api/v1/weather", params={"farm_id": fid})
    assert stale.json()["data"]["stale"] is True


@pytest.mark.usefixtures("test_db")
async def test_weather_access_rules(make_user: UserFactory) -> None:
    farmer, _ = await make_user("farmer")
    other, _ = await make_user("farmer")
    farm = await farmer.post(
        "/api/v1/farms",
        json={"name": "P", "district": "Hooghly", "location": {"lat": 22.9, "lng": 88.39}},
    )
    fid = farm.json()["data"]["id"]
    assert (await other.get("/api/v1/weather", params={"farm_id": fid})).status_code == 404
    outside = await farmer.get("/api/v1/weather", params={"lat": 28.6, "lng": 77.2})
    assert outside.status_code == 422
    g = await farmer.get("/api/v1/advisories/guidance/potato/late_blight")
    assert g.json()["data"]["entry"]["crop"] == "potato"
    assert (await farmer.get("/api/v1/advisories/guidance/potato/..%2F")).status_code == 404
