"""Pure-ASGI middleware: security headers and request body size limits.

Pure ASGI (not BaseHTTPMiddleware) so WebSockets and streaming are untouched.
"""

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Only the third-party origins the frontend actually uses.
CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' https://unpkg.com https://cdn.jsdelivr.net",
        "style-src 'self' https://fonts.googleapis.com https://unpkg.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: blob: https://tile.openstreetmap.org https://unpkg.com",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
# Swagger UI (/docs, kept on for judges) ships inline scripts; it gets every header except CSP.
CSP_EXEMPT_PREFIXES = ("/docs", "/redoc", "/openapi.json")


class SecurityHeaders:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}

                def add(name: str, value: str) -> None:
                    if name.encode() not in present:
                        headers.append((name.encode(), value.encode()))

                add("x-content-type-options", "nosniff")
                add("x-frame-options", "DENY")
                # QR tokens travel in ?t=…; never send full URLs to other origins.
                add("referrer-policy", "same-origin")
                add("permissions-policy", "camera=(self), geolocation=(self), microphone=()")
                add("cross-origin-opener-policy", "same-origin")
                if not path.startswith(CSP_EXEMPT_PREFIXES):
                    add("content-security-policy", CSP)
                if path.startswith("/api/"):
                    add("cache-control", "no-store")
                if self.hsts:
                    add("strict-transport-security", "max-age=31536000; includeSubDomains")
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def _reject(send: Send, status: int, code: str, message: str) -> None:
    body = json.dumps({"error": {"code": code, "message": message, "details": None}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodySizeLimit:
    """Rejects oversized bodies (declared or streamed) with the standard error envelope."""

    def __init__(
        self, app: ASGIApp, *, default: int = 256 * 1024, multipart: int = 3 * 1024 * 1024
    ) -> None:
        self.app = app
        self.default = default
        self.multipart = multipart

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers: dict[bytes, bytes] = {k.lower(): v for k, v in scope.get("headers", [])}
        ctype = headers.get(b"content-type", b"").lower()
        limit = self.multipart if ctype.startswith(b"multipart/form-data") else self.default

        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                size = int(declared)
            except ValueError:
                await _reject(send, 400, "bad_request", "Invalid Content-Length")
                return
            if size > limit:
                await _reject(send, 413, "payload_too_large", "Request body is too large")
                return

        # Streamed (chunked) bodies: count bytes as they arrive. On overflow we answer 413
        # ourselves, end the stream with a disconnect, and drop whatever the app sends after
        # (FastAPI would otherwise turn the read error into its own 400).
        received = 0
        started = False
        rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected, started
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    rejected = True
                    if not started:
                        started = True
                        await _reject(send, 413, "payload_too_large", "Request body is too large")
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, limited_receive, tracking_send)
