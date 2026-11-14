"""Background loops started in the FastAPI lifespan (planning §6: asyncio tasks, no Celery)."""

import asyncio
import logging

from pymongo.asynchronous.database import AsyncDatabase

from backend.app.db.client import Doc
from backend.app.modules.aquasentinel import service as aquasentinel
from backend.app.modules.freshtrack import service as freshtrack

log = logging.getLogger("irminsul.scheduler")
STALE_CHECK_EVERY_S = 60
HEAVY_RAIN_CHECK_EVERY_S = 3600  # forecasts are cached for 1 h anyway


async def stale_sensor_loop(db: AsyncDatabase[Doc]) -> None:
    while True:
        try:
            await freshtrack.check_stale(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Stale-sensor check failed")
        await asyncio.sleep(STALE_CHECK_EVERY_S)


async def heavy_rain_loop(db: AsyncDatabase[Doc]) -> None:
    await asyncio.sleep(30)  # let startup finish first
    while True:
        try:
            await aquasentinel.check_heavy_rain(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Heavy-rain check failed")
        await asyncio.sleep(HEAVY_RAIN_CHECK_EVERY_S)
