"""FreshTrack engine: duration/severity, stale detection, implausible, unusual (planning §13)."""

from datetime import UTC, datetime, timedelta

from backend.app.modules.freshtrack import engine, rules
from backend.app.modules.freshtrack.engine import Reading

T0 = datetime(2026, 11, 14, 6, 0, tzinfo=UTC)
D = rules.defaults()
POTATO = rules.profile_for("potato")  # table potato 3-5 C, RH 90-95 %


def series(temps: list[float], step_min: int = 5, rh: float = 92) -> list[Reading]:
    return [Reading(T0 + timedelta(minutes=i * step_min), t, rh) for i, t in enumerate(temps)]


def test_rules_are_cited() -> None:
    data = rules.load()
    for pid, p in data["profiles"].items():
        assert p["source"]["url"].startswith("https://"), pid
        assert "verified" in p, pid
    assert POTATO is not None and (POTATO["temp_min_c"], POTATO["temp_max_c"]) == (3.0, 5.0)
    assert POTATO["verified"] is True


def test_in_band_has_no_findings() -> None:
    assert engine.evaluate(series([4.0] * 20), POTATO, D) == []


def test_short_excursion_does_not_alert_yet() -> None:
    r = series([4.0] * 5 + [6.5] * 5)  # 20 minutes above
    assert engine.excursions(r, POTATO, D) == []


def test_warning_then_critical_by_duration() -> None:
    warn = engine.excursions(series([4.0] * 3 + [6.5] * 9), POTATO, D)  # 40 min above
    assert [(f.kind, f.severity) for f in warn] == [("temp_high", "warning")]
    assert warn[0].duration_min == 40
    assert warn[0].threshold == 5.0
    crit = engine.excursions(series([4.0] * 3 + [6.5] * 26 + [7.1]), POTATO, D)  # 135 min
    assert crit[0].severity == "critical"
    assert crit[0].peak == 7.1


def test_excursion_ends_when_back_in_band() -> None:
    assert engine.excursions(series([6.5] * 20 + [4.0]), POTATO, D) == []


def test_low_temp_and_humidity_bands() -> None:
    cold = engine.excursions(series([2.0] * 10), POTATO, D)
    assert cold[0].kind == "temp_low"
    dry = engine.excursions(series([4.0] * 10, rh=80), POTATO, D)
    assert dry[0].kind == "rh_low"


def test_profile_without_band_only_checks_sensor() -> None:
    rice = rules.profile_for("rice")
    assert rice is not None and rice["temp_max_c"] is None
    assert engine.excursions(series([45.0] * 30), rice, D) == []


def test_stale_detection() -> None:
    assert engine.stale(T0, T0 + timedelta(minutes=29), D) is None
    s = engine.stale(T0, T0 + timedelta(minutes=45), D)
    assert s is not None and s.kind == "stale" and s.duration_min == 45
    assert engine.stale(None, T0, D) is None


def test_implausible_values_and_jumps() -> None:
    hot = engine.implausible(Reading(T0, 80.0, 92), None, D)
    assert hot is not None and "temp_out_of_plausible_range" in hot.details["reasons"]
    jump = engine.implausible(Reading(T0 + timedelta(minutes=5), 15.0, 92), Reading(T0, 4.0, 92), D)
    assert jump is not None and jump.details["reasons"] == ["temp_jump"]
    slow = engine.implausible(
        Reading(T0 + timedelta(minutes=60), 15.0, 92), Reading(T0, 4.0, 92), D
    )
    assert slow is None


def test_unusual_is_info_only() -> None:
    r = series([4.0, 4.1, 3.9, 4.0, 4.05, 3.95] * 3 + [4.9])
    f = engine.unusual(r, D)
    assert f is not None and f.severity == "info"
    assert engine.unusual(series([4.0] * 5 + [4.9]), D) is None  # too few points


def test_summary() -> None:
    s = engine.summarise(series([4.0, 4.5, 6.0, 4.2]), POTATO)
    assert s["temp_in_band_pct"] == 75.0
    assert s["status"] == "excursions"
    assert engine.summarise([], POTATO)["status"] == "no_readings"
