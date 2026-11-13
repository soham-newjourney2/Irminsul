"""FastAPI entrypoint: /api/v1 + static frontend (WebSocket hub arrives in M2)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.config import get_settings
from backend.app.core.errors import install_error_handlers
from backend.app.db.client import mongo
from backend.app.db.indexes import ensure_indexes
from backend.app.modules.health.router import router as health_router

log = logging.getLogger("irminsul")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    await mongo.connect(settings)
    if mongo.db is None:
        log.warning("MONGODB_URI not set: running without a database")
    else:
        try:
            await ensure_indexes(mongo.db)
        except Exception:
            log.exception("Index creation failed; health will report the DB state")
    try:
        yield
    finally:
        await mongo.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Irminsul API", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(health_router, prefix="/api/v1")
    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    return app


app = create_app()
