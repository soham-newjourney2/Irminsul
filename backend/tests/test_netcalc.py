"""Net realization arithmetic + distance fallback (planning §13)."""

import httpx
import pytest

from backend.app.integrations import osrm
from backend.app.modules.mandi.netcalc import NetRealization, compute


def _calc(**kw: float) -> NetRealization:
    base = {
        "qty_kg": 1000,  # 10 quintal
        "modal_price_paise_per_quintal": 150000,  # Rs 1,500 / q
        "distance_km": 40.0,
        "distance_source": "osrm",
        "transport_rate_paise_per_km_per_quintal": 300,  # Rs 3 / km / q
        "fees_pct": 2.0,
        "practical_distance_km": 150.0,
    }
    return compute(**(base | kw))  # type: ignore[arg-type]  # test-only kwargs merge


def test_breakdown() -> None:
    r = _calc()
    assert r.gross_paise == 1_500_000  # 10 q x Rs 1,500 = Rs 15,000
    assert r.transport_paise == 120_000  # 40 km x Rs 3 x 10 q = Rs 1,200
    assert r.fees_paise == 30_000  # 2 % of Rs 15,000 = Rs 300
    assert r.net_paise == 1_350_000  # Rs 13,500
    assert r.beyond_practical_distance is False


def test_far_market_flagged_not_hidden() -> None:
    r = _calc(distance_km=220.0)
    assert r.beyond_practical_distance is True
    assert r.net_paise == 1_500_000 - 660_000 - 30_000


def test_partial_quintal_rounding() -> None:
    r = _calc(qty_kg=125, distance_km=12.5)
    assert r.gross_paise == 187_500  # 1.25 q x Rs 1,500
    assert r.transport_paise == 4_688  # 12.5 x 300 x 1.25 = 4687.5 → half-up


@pytest.mark.parametrize(
    "bad",
    [
        {"qty_kg": 0},
        {"modal_price_paise_per_quintal": -1},
        {"fees_pct": 101.0},
        {"distance_km": -1.0},
    ],
)
def test_rejects_bad_inputs(bad: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        _calc(**bad)


def test_haversine_estimate_is_labelled() -> None:
    d = osrm.estimate(22.90, 88.39, 22.57, 88.36)
    assert d.source == "haversine_estimate"
    assert 45 < d.km < 50  # ~36.8 km great-circle x 1.3


async def test_osrm_success_and_fallback() -> None:
    ok = {"code": "Ok", "routes": [{"distance": 46647.8, "duration": 3005.3}]}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=ok))
    ) as c:
        d = await osrm.road_distance(22.9, 88.39, 22.57, 88.36, client=c)
    assert (d.km, d.source, d.duration_min) == (46.6, "osrm", 50.0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429))) as c:
        d = await osrm.road_distance(22.9, 88.39, 22.57, 88.36, client=c)
    assert d.source == "haversine_estimate"
    bad = {"code": "NoRoute", "routes": []}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=bad))
    ) as c:
        d = await osrm.road_distance(22.9, 88.39, 22.57, 88.36, client=c)
    assert d.source == "haversine_estimate"
