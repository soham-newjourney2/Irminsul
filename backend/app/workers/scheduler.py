"""Background loops started in the FastAPI lifespan (planning §6: asyncio tasks, no Celery)."""

import asyncio
import logging

from pymongo.asynchronous.database import AsyncDatabase

from backend.app.db.client import Doc
from backend.app.modules.freshtrack import service as freshtrack

log = logging.getLogger("irminsul.scheduler")
STALE_CHECK_EVERY_S = 60


async def stale_sensor_loop(db: AsyncDatabase[Doc]) -> None:
    while True:
        try:
            await freshtrack.check_stale(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Stale-sensor check failed")
        await asyncio.sleep(STALE_CHECK_EVERY_S)
