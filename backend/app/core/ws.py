"""In-memory WebSocket hub (single instance). Messages: {"type": ..., "data": ...}."""

import logging
from collections import defaultdict
from typing import Any, Protocol

log = logging.getLogger("irminsul.ws")


class Socket(Protocol):
    async def send_json(self, data: Any, mode: str = "text") -> None: ...


class Hub:
    def __init__(self) -> None:
        self._conns: defaultdict[str, set[Socket]] = defaultdict(set)

    def connect(self, user_id: str, ws: Socket) -> None:
        self._conns[user_id].add(ws)

    def disconnect(self, user_id: str, ws: Socket) -> None:
        conns = self._conns.get(user_id)
        if conns is None:
            return
        conns.discard(ws)
        if not conns:
            del self._conns[user_id]

    def connected_users(self) -> int:
        return len(self._conns)

    async def _send(self, user_id: str, ws: Socket, message: dict[str, Any]) -> None:
        try:
            await ws.send_json(message)
        except Exception:
            log.debug("Dropping dead socket for user %s", user_id)
            self.disconnect(user_id, ws)

    async def send_user(self, user_id: str, message: dict[str, Any]) -> None:
        for ws in list(self._conns.get(user_id, ())):
            await self._send(user_id, ws, message)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for user_id, conns in list(self._conns.items()):
            for ws in list(conns):
                await self._send(user_id, ws, message)


hub = Hub()
