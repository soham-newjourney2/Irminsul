"""FreshTrack alert engine — pure functions, no I/O.

Findings explain themselves: condition, time window, threshold, peak. An "unusual" flag is an
investigation signal only, never a food-safety verdict.
"""

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

Kind = Literal["temp_high", "temp_low", "rh_high", "rh_low", "implausible", "unusual", "stale"]
Severity = Literal["info", "warning", "critical"]


@dataclass(frozen=True)
class Reading:
    observed_at: datetime
    temp_c: float | None
    rh_pct: float | None


@dataclass(frozen=True)
class Finding:
    kind: Kind
    severity: Severity
    metric: str | None
    threshold: float | None
    peak: float | None
    started_at: datetime
    latest_at: datetime
    duration_min: float
    details: dict[str, Any] = field(default_factory=dict)


BANDS = (
    ("temp_c", "temp_high", "temp_max_c", 1),
    ("temp_c", "temp_low", "temp_min_c", -1),
    ("rh_pct", "rh_high", "rh_max", 1),
    ("rh_pct", "rh_low", "rh_min", -1),
)


def _outside(value: float | None, limit: float, direction: int) -> bool:
    if value is None:
        return False
    return value > limit if direction > 0 else value < limit


def excursions(
    readings: list[Reading], profile: dict[str, Any] | None, d: dict[str, Any]
) -> list[Finding]:
    """Continuous out-of-band run ending at the latest reading → warning/critical by duration."""
    if not readings or profile is None:
        return []
    out: list[Finding] = []
    latest = readings[-1]
    for metric, kind, key, direction in BANDS:
        limit = profile.get(key)
        if limit is None or not _outside(getattr(latest, metric), limit, direction):
            continue
        start = latest
        peak = getattr(latest, metric)
        for r in reversed(readings[:-1]):
            v = getattr(r, metric)
            if not _outside(v, limit, direction):
                break
            start = r
            peak = max(peak, v) if direction > 0 else min(peak, v)
        minutes = (latest.observed_at - start.observed_at).total_seconds() / 60
        if minutes >= d["critical_after_minutes"]:
            severity: Severity = "critical"
        elif minutes >= d["warning_after_minutes"]:
            severity = "warning"
        else:
            continue  # out of band, but not yet for long enough to alert
        out.append(
            Finding(
                kind=kind,  # type: ignore[arg-type]
                severity=severity,
                metric=metric,
                threshold=float(limit),
                peak=float(peak),
                started_at=start.observed_at,
                latest_at=latest.observed_at,
                duration_min=round(minutes, 1),
                details={
                    "warning_after_minutes": d["warning_after_minutes"],
                    "critical_after_minutes": d["critical_after_minutes"],
                },
            )
        )
    return out


def implausible(latest: Reading, previous: Reading | None, d: dict[str, Any]) -> Finding | None:
    p = d["plausible"]
    reasons = []
    if latest.temp_c is not None and not (p["temp_min_c"] <= latest.temp_c <= p["temp_max_c"]):
        reasons.append("temp_out_of_plausible_range")
    if latest.rh_pct is not None and not (p["rh_min"] <= latest.rh_pct <= p["rh_max"]):
        reasons.append("rh_out_of_plausible_range")
    if (
        previous is not None
        and latest.temp_c is not None
        and previous.temp_c is not None
        and latest.observed_at - previous.observed_at <= timedelta(minutes=p["jump_window_minutes"])
        and abs(latest.temp_c - previous.temp_c) > p["max_jump_c"]
    ):
        reasons.append("temp_jump")
    if not reasons:
        return None
    return Finding(
        kind="implausible",
        severity="warning",
        metric="temp_c" if any(r.startswith("temp") for r in reasons) else "rh_pct",
        threshold=None,
        peak=latest.temp_c,
        started_at=latest.observed_at,
        latest_at=latest.observed_at,
        duration_min=0,
        details={"reasons": reasons, "previous_temp_c": previous.temp_c if previous else None},
    )


def unusual(readings: list[Reading], d: dict[str, Any]) -> Finding | None:
    u = d["unusual"]
    history = [r.temp_c for r in readings[-(u["window"] + 1) : -1] if r.temp_c is not None]
    latest = readings[-1] if readings else None
    if latest is None or latest.temp_c is None or len(history) < u["min_points"]:
        return None
    mean = statistics.fmean(history)
    sd = statistics.pstdev(history)
    if sd == 0 or abs(latest.temp_c - mean) <= u["sigma"] * sd:
        return None
    return Finding(
        kind="unusual",
        severity="info",
        metric="temp_c",
        threshold=round(mean + (u["sigma"] * sd if latest.temp_c > mean else -u["sigma"] * sd), 2),
        peak=latest.temp_c,
        started_at=latest.observed_at,
        latest_at=latest.observed_at,
        duration_min=0,
        details={
            "mean": round(mean, 2),
            "stdev": round(sd, 3),
            "sigma": u["sigma"],
            "points": len(history),
        },
    )


def stale(last_observed_at: datetime | None, now: datetime, d: dict[str, Any]) -> Finding | None:
    if last_observed_at is None:
        return None
    gap = (now - last_observed_at).total_seconds() / 60
    if gap < d["stale_after_minutes"]:
        return None
    return Finding(
        kind="stale",
        severity="warning",
        metric=None,
        threshold=float(d["stale_after_minutes"]),
        peak=None,
        started_at=last_observed_at,
        latest_at=now,
        duration_min=round(gap, 1),
        details={"last_reading_at": last_observed_at.isoformat()},
    )


def evaluate(
    readings: list[Reading], profile: dict[str, Any] | None, d: dict[str, Any]
) -> list[Finding]:
    """All findings for the latest reading (readings sorted ascending by observed_at)."""
    if not readings:
        return []
    found = excursions(readings, profile, d)
    imp = implausible(readings[-1], readings[-2] if len(readings) > 1 else None, d)
    if imp:
        found.append(imp)
    else:  # an implausible value is a sensor question; do not also call it statistically unusual
        u = unusual(readings, d)
        if u:
            found.append(u)
    return found


def summarise(readings: list[Reading], profile: dict[str, Any] | None) -> dict[str, Any]:
    temps = [r.temp_c for r in readings if r.temp_c is not None]
    rhs = [r.rh_pct for r in readings if r.rh_pct is not None]
    in_band = None
    if profile and profile.get("temp_min_c") is not None and temps:
        ok = sum(1 for t in temps if profile["temp_min_c"] <= t <= profile["temp_max_c"])
        in_band = round(100 * ok / len(temps), 1)
    return {
        "readings": len(readings),
        "temp_min_c": min(temps) if temps else None,
        "temp_max_c": max(temps) if temps else None,
        "temp_mean_c": round(statistics.fmean(temps), 2) if temps else None,
        "rh_min": min(rhs) if rhs else None,
        "rh_max": max(rhs) if rhs else None,
        "temp_in_band_pct": in_band,
        "status": "no_readings"
        if not readings
        else ("within_band" if in_band in (None, 100.0) else "excursions"),
    }
