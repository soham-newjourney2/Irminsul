"""Pure advisory engine: forecast + rules → explainable advisories. No I/O."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.config import REPO_ROOT

RULES_PATH = REPO_ROOT / "data" / "advisory_rules.json"


@dataclass(frozen=True)
class Advisory:
    rule_id: str
    kind: str
    severity: str
    crop: str | None
    disease: str | None
    label: str | None
    evidence: dict[str, Any]
    window_start: str
    window_end: str
    source: dict[str, Any]
    verified: bool
    assumptions: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def load_rules(path: Path = RULES_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["rules"]


def _hours(forecast: dict[str, Any], now_local: datetime, window: int) -> list[dict[str, Any]]:
    h = forecast["hourly"]
    start = now_local.replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=window)
    rows = []
    for i, ts in enumerate(h["time"]):
        t = datetime.fromisoformat(ts)
        if start <= t < end:
            rows.append(
                {
                    "time": ts,
                    "temp": h["temperature_2m"][i],
                    "rh": h["relative_humidity_2m"][i],
                    "rain": h["precipitation"][i],
                }
            )
    return rows


def _matches(row: dict[str, Any], cond: dict[str, Any]) -> bool:
    if row["temp"] is None or row["rh"] is None:
        return False
    if "rh_min" in cond and row["rh"] < cond["rh_min"]:
        return False
    return cond.get("temp_min", -99) <= row["temp"] <= cond.get("temp_max", 99)


def evaluate(
    forecast: dict[str, Any], crops: list[str], now_local: datetime, rules: list[dict[str, Any]]
) -> list[Advisory]:
    """now_local must be naive local time in the forecast's timezone (Asia/Kolkata)."""
    out: list[Advisory] = []
    for rule in rules:
        rule_crops = rule.get("crops")
        applicable = [None] if rule_crops is None else [c for c in rule_crops if c in crops]
        if not applicable:
            continue
        base = {
            "source": rule["source"],
            "verified": bool(rule.get("verified", False)),
            "assumptions": list(rule.get("assumptions", [])),
        }
        if rule["metric"] == "daily_precipitation_mm":
            d = forecast["daily"]
            today = now_local.date().isoformat()
            for i, day in enumerate(d["time"]):
                if day < today:
                    continue
                mm = d["precipitation_sum"][i]
                if mm is None:
                    continue
                band = None
                for b in sorted(rule["bands"], key=lambda b: b["min"]):
                    if mm >= b["min"]:
                        band = b
                if band:
                    out.append(
                        Advisory(
                            rule_id=rule["id"],
                            kind=rule["kind"],
                            severity=band["severity"],
                            crop=None,
                            disease=None,
                            label=band["label"],
                            evidence={
                                "date": day,
                                "precipitation_mm": mm,
                                "threshold_mm": band["min"],
                            },
                            window_start=day,
                            window_end=day,
                            **base,
                        )
                    )
            continue

        rows = _hours(forecast, now_local, int(rule["window_hours"]))
        if not rows:
            continue
        matching = [r for r in rows if _matches(r, rule["hourly_condition"])]
        rain_total = round(sum(r["rain"] or 0 for r in rows), 1)
        triggered = len(matching) >= rule["trigger_hours"]
        if rule["metric"] == "hours_matching_with_rain":
            triggered = triggered and rain_total >= rule.get("rain_mm_min", 0.1)
        if not triggered:
            continue
        for crop in applicable:
            out.append(
                Advisory(
                    rule_id=rule["id"],
                    kind=rule["kind"],
                    severity=rule["severity"],
                    crop=crop,
                    disease=rule.get("disease"),
                    label=None,
                    evidence={
                        "matching_hours": len(matching),
                        "window_hours": len(rows),
                        "trigger_hours": rule["trigger_hours"],
                        "condition": rule["hourly_condition"],
                        "rain_mm_in_window": rain_total,
                        "first_matching_hour": matching[0]["time"],
                    },
                    window_start=rows[0]["time"],
                    window_end=rows[-1]["time"],
                    **base,
                )
            )
    return out
