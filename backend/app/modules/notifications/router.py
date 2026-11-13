from typing import Annotated
from urllib.parse import urlsplit

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from backend.app.config import get_settings
from backend.app.core.deps import ActiveUser, Db
from backend.app.core.schemas import Envelope
from backend.app.core.security import decode_session_token
from backend.app.core.ws import hub
from backend.app.db.client import mongo
from backend.app.modules.notifications import service
from backend.app.modules.notifications.schemas import MarkReadIn, NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])
ws_router = APIRouter(tags=["realtime"])


@router.get("", response_model=Envelope[list[NotificationOut]])
async def list_notifications(
    user: ActiveUser,
    db: Db,
    unread: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> Envelope[list[NotificationOut]]:
    rows, unread_count = await service.list_for_user(db, user["_id"], unread, limit)
    return Envelope(data=rows, meta={"unread": unread_count})


@router.post("/read", response_model=Envelope[dict[str, int]])
async def mark_read(body: MarkReadIn, user: ActiveUser, db: Db) -> Envelope[dict[str, int]]:
    ids = None
    if body.ids is not None:
        ids = []
        for raw in body.ids[:100]:
            try:
                ids.append(ObjectId(raw))
            except InvalidId:
                continue
    changed = await service.mark_read(db, user["_id"], ids)
    return Envelope(data={"marked": changed})


def _same_origin(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return True  # non-browser clients
    return urlsplit(origin).netloc == ws.headers.get("host")


@ws_router.websocket("/ws")
async def websocket(ws: WebSocket) -> None:
    settings = get_settings()
    token = ws.cookies.get(settings.session_cookie_name)
    claims = decode_session_token(token, settings) if token else None
    user = None
    if claims and mongo.db is not None and _same_origin(ws):
        try:
            user = await mongo.db.users.find_one({"_id": ObjectId(str(claims["sub"]))})
        except InvalidId:
            user = None
    if user is None or user.get("status") != "active":
        await ws.close(code=4401)
        return

    await ws.accept()
    uid = str(user["_id"])
    hub.connect(uid, ws)
    try:
        while True:
            await ws.receive_text()  # client pings; content ignored
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(uid, ws)
