"""Demo sensor simulator. Every reading it writes is source="simulated".

Single-instance, in-memory task registry (no Celery/Redis).
"""

import asyncio
import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from backend.app.db.client import Doc
from backend.app.modules.freshtrack import service

log = logging.getLogger("irminsul.simulator")
_tasks: dict[str, asyncio.Task[None]] = {}
_rng = random.Random()  # noqa: S311 — demo sensor noise, not security-related


def running() -> list[str]:
    return [z for z, t in _tasks.items() if not t.done()]


def _normal(profile: dict[str, Any] | None) -> tuple[float, float]:
    if profile and profile.get("temp_min_c") is not None:
        t = (profile["temp_min_c"] + profile["temp_max_c"]) / 2 + _rng.gauss(0, 0.12)
    else:
        t = 28 + _rng.gauss(0, 0.8)
    if profile and profile.get("rh_min") is not None and profile.get("rh_max") is not None:
        rh = (profile["rh_min"] + profile["rh_max"]) / 2 + _rng.gauss(0, 0.6)
    elif profile and profile.get("rh_max") is not None:
        rh = profile["rh_max"] - 8 + _rng.gauss(0, 1.5)
    else:
        rh = 60 + _rng.gauss(0, 2)
    return round(t, 2), round(min(max(rh, 5), 100), 1)


async def _loop(db: AsyncDatabase[Doc], zone_id: ObjectId, interval_s: int) -> None:
    while True:
        try:
            ctx = await service.zone_context(db, zone_id)
            t, rh = _normal(ctx["profile"])
            await service.record(db, ctx, datetime.now(UTC), t, rh, "simulated", None)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Simulator tick failed for zone %s", zone_id)
        await asyncio.sleep(interval_s)


def start(db: AsyncDatabase[Doc], zone_id: ObjectId, interval_s: int) -> bool:
    key = str(zone_id)
    if key in running():
        return False
    _tasks[key] = asyncio.create_task(_loop(db, zone_id, interval_s), name=f"sim-{key}")
    return True


def stop(zone_id: ObjectId) -> bool:
    task = _tasks.pop(str(zone_id), None)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def stop_all() -> None:
    for key in list(_tasks):
        _tasks.pop(key).cancel()


async def inject(
    db: AsyncDatabase[Doc], zone_id: ObjectId, kind: str, minutes: int, magnitude: float
) -> list[Doc]:
    """Write a labelled simulated excursion covering the last `minutes` (5-minute steps).

    Earlier *simulated* readings inside that window are flagged superseded (never deleted) so the
    injected run is continuous. Manual readings are never touched.
    """
    ctx = await service.zone_context(db, zone_id)
    p = ctx["profile"] or {}
    now = datetime.now(UTC)
    start_at = now - timedelta(minutes=minutes)
    await db.storage_observations.update_many(
        {"zone_id": zone_id, "source": "simulated", "observed_at": {"$gte": start_at}},
        {"$set": {"superseded": True}},
    )
    steps = minutes // 5
    for i in range(steps + 1):
        at = start_at + timedelta(minutes=5 * i)
        t, rh = _normal(ctx["profile"])
        if kind == "temp_high" and p.get("temp_max_c") is not None:
            t = p["temp_max_c"] + magnitude + _rng.gauss(0, 0.1)
        elif kind == "temp_low" and p.get("temp_min_c") is not None:
            t = p["temp_min_c"] - magnitude + _rng.gauss(0, 0.1)
        elif kind == "rh_high" and p.get("rh_max") is not None:
            rh = min(100, p["rh_max"] + magnitude)
        elif kind == "rh_low" and p.get("rh_min") is not None:
            rh = max(5, p["rh_min"] - magnitude)
        elif kind == "implausible" and i == steps:
            t = 85.0
        await service.record(
            db, ctx, at, t, rh, "simulated", None, note=f"injected {kind}", process=False
        )
    return await service.process_zone(db, ctx, simulated=True)
