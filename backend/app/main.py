"""FastAPI entrypoint: /api/v1, /ws, and the static frontend."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.config import get_settings
from backend.app.core.errors import install_error_handlers
from backend.app.db.client import mongo
from backend.app.db.indexes import ensure_indexes
from backend.app.modules.admin.router import router as admin_router
from backend.app.modules.auth.router import router as auth_router
from backend.app.modules.batches.router import public_router as qr_router
from backend.app.modules.batches.router import router as batches_router
from backend.app.modules.farms.router import router as farms_router
from backend.app.modules.health.router import router as health_router
from backend.app.modules.listings.router import router as listings_router
from backend.app.modules.notifications.router import router as notifications_router
from backend.app.modules.notifications.router import ws_router
from backend.app.modules.procurement.router import orders_router, requests_router
from backend.app.modules.storage.router import router as storage_router
from backend.app.modules.users.router import router as users_router

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
    api_routers = (
        health_router,
        auth_router,
        users_router,
        admin_router,
        farms_router,
        listings_router,
        requests_router,
        orders_router,
        storage_router,
        notifications_router,
        batches_router,
        qr_router,
    )
    for router in api_routers:
        app.include_router(router, prefix="/api/v1")
    app.include_router(ws_router)
    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    return app


app = create_app()
